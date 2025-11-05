"""
Streamable HTTP transport for Garmin MCP (Model Context Protocol).

Implements the official MCP Streamable HTTP specification:
- Single /mcp endpoint for all JSON-RPC communication
- POST /mcp: accepts JSON-RPC requests, responds with JSON or SSE
- GET /mcp: optional persistent SSE stream for server notifications
- /healthz: health check endpoint (separate from /mcp)

This module reuses all tool handlers from the FastMCP app,
avoiding code duplication while providing HTTP transport.
"""

import asyncio
import json
import logging
import sys
from typing import Any, Optional

from fastapi import FastAPI, Request, Response, Header
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.status import HTTP_202_ACCEPTED, HTTP_400_BAD_REQUEST, HTTP_500_INTERNAL_SERVER_ERROR
import uvicorn

from mcp.server.fastmcp import FastMCP

# Import utility functions
from garmin_mcp.utils.sse import format_sse_event, format_sse_error
from garmin_mcp.utils.jsonrpc import (
    is_valid_jsonrpc, is_notification,
    create_success_response, create_error_response,
    validate_mcp_protocol_version, JsonRpcError
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Global state (initialized at startup)
mcp_app: Optional[FastMCP] = None
fastapi_app = FastAPI(title="Garmin MCP Server - Streamable HTTP")


async def get_tools_list() -> list:
    """Get list of whitelisted MCP tools from the app"""
    from garmin_mcp import get_whitelisted_tools
    
    if not mcp_app:
        raise RuntimeError("MCP app not initialized")
    
    tools = await get_whitelisted_tools(mcp_app)
    return tools


async def call_tool_handler(name: str, arguments: dict[str, Any]) -> list:
    """
    Call tool handler using FastMCP app.
    
    Args:
        name: Tool name
        arguments: Tool arguments
        
    Returns:
        List of content items (MCP format)
    """
    if not mcp_app:
        raise RuntimeError("MCP app not initialized")
    
    # Call the tool through FastMCP
    raw_result = await mcp_app.call_tool(name, arguments)
    
    # Normalize tool result to MCP-compatible shape: { content: [ { type: 'text', text: ... } ] }
    if (
        isinstance(raw_result, dict)
        and "content" in raw_result
        and isinstance(raw_result["content"], list)
    ):
        # Already in correct format
        return raw_result["content"]
    else:
        # Convert to MCP content format
        if not isinstance(raw_result, str):
            try:
                text = json.dumps(raw_result, indent=2, ensure_ascii=False)
            except Exception:
                text = str(raw_result)
        else:
            text = raw_result
        
        return [{"type": "text", "text": text}]


async def handle_mcp_request(request_data: dict) -> dict:
    """
    Handle a single MCP JSON-RPC request.
    Routes to appropriate handler based on method.
    
    Returns JSON-RPC response dict.
    """
    method = request_data.get("method")
    params = request_data.get("params", {})
    request_id = request_data.get("id")
    
    try:
        # Route to appropriate handler
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                },
                "serverInfo": {
                    "name": "garmin-mcp-server",
                    "version": "1.0.0"
                }
            }
            return create_success_response(request_id, result)
        
        elif method == "ping":
            # Ping notification - no response needed
            return None
        
        elif method == "tools/list":
            tools = await get_tools_list()
            return create_success_response(request_id, {"tools": tools})
        
        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            
            if not tool_name:
                return create_error_response(
                    request_id, JsonRpcError.INVALID_PARAMS, "Missing tool name"
                )
            
            # Call tool handler
            content_list = await call_tool_handler(tool_name, tool_args)
            
            return create_success_response(request_id, {"content": content_list})
        
        elif method == "notifications/initialized":
            # Client notification that it's ready - no response needed
            return None
        
        else:
            return create_error_response(
                request_id, JsonRpcError.METHOD_NOT_FOUND, f"Unknown method: {method}"
            )
    
    except Exception as e:
        logger.error(f"Error handling method {method}: {e}", exc_info=True)
        return create_error_response(
            request_id, JsonRpcError.INTERNAL_ERROR, str(e)
        )


@fastapi_app.post("/mcp")
async def mcp_post_endpoint(
    request: Request,
    mcp_protocol_version: Optional[str] = Header(None, alias="MCP-Protocol-Version")
):
    """
    POST /mcp - Main MCP endpoint for JSON-RPC requests.
    
    Accepts:
    - Content-Type: application/json
    - MCP-Protocol-Version header (optional but recommended)
    
    Returns:
    - 202 Accepted (for notifications - no response body)
    - 200 OK with Content-Type: application/json (for requests)
    """
    
    # Validate protocol version if provided
    if mcp_protocol_version and not validate_mcp_protocol_version(mcp_protocol_version):
        return JSONResponse(
            status_code=HTTP_400_BAD_REQUEST,
            content=create_error_response(
                None, JsonRpcError.INVALID_REQUEST,
                f"Unsupported MCP protocol version: {mcp_protocol_version}"
            )
        )
    
    # Parse request body
    try:
        body = await request.json()
    except json.JSONDecodeError as e:
        return JSONResponse(
            status_code=HTTP_400_BAD_REQUEST,
            content=create_error_response(
                None, JsonRpcError.PARSE_ERROR, f"Invalid JSON: {str(e)}"
            )
        )
    
    # Validate JSON-RPC structure
    if not is_valid_jsonrpc(body):
        return JSONResponse(
            status_code=HTTP_400_BAD_REQUEST,
            content=create_error_response(
                body.get("id"), JsonRpcError.INVALID_REQUEST, "Invalid JSON-RPC request"
            )
        )
    
    # Check if notification (no response expected)
    if is_notification(body):
        # Handle notification asynchronously, return 202 immediately
        asyncio.create_task(handle_mcp_request(body))
        return Response(status_code=HTTP_202_ACCEPTED)
    
    # Handle request and return response
    response = await handle_mcp_request(body)
    
    if response is None:
        # Shouldn't happen for requests (only notifications), but handle gracefully
        return Response(status_code=HTTP_202_ACCEPTED)
    
    return JSONResponse(content=response)


@fastapi_app.get("/mcp")
async def mcp_get_endpoint():
    """
    GET /mcp - Optional persistent SSE stream for server-initiated notifications.
    
    This is optional per MCP spec. Currently returns empty SSE stream.
    Can be extended later for server push notifications.
    """
    async def event_generator():
        # Keep connection alive with periodic comments
        while True:
            yield ": keepalive\n\n"
            await asyncio.sleep(30)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )


@fastapi_app.get("/healthz")
async def health_check():
    """Health check endpoint (separate from /mcp per MCP guide)"""
    try:
        if mcp_app:
            return JSONResponse(content={
                "status": "healthy",
                "app": "initialized"
            })
        else:
            return JSONResponse(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                content={"status": "unhealthy", "error": "MCP app not initialized"}
            )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": "unhealthy", "error": str(e)}
        )


def run_http_server(app: FastMCP, host: str = "127.0.0.1", port: int = 5000):
    """
    Run the Garmin MCP server with Streamable HTTP transport.
    
    Args:
        app: FastMCP app instance with all tools registered
        host: Host to bind to
        port: Port to listen on
    """
    global mcp_app
    mcp_app = app
    
    logger.info(f"Garmin MCP Server (HTTP) starting on http://{host}:{port}/mcp")
    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")
