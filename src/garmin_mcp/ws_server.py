"""
WebSocket server wrapper for Garmin MCP with JSON-RPC 2.0 support
"""

import asyncio
import json
import logging
import sys
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="[%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("garmin-ws")


def create_json_rpc_response(
    id: int | str | None, result: Any = None, error: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    """Create a JSON-RPC 2.0 response"""
    response: Dict[str, Any] = {"jsonrpc": "2.0"}

    if id is not None:
        response["id"] = id

    if error:
        response["error"] = error
    else:
        response["result"] = result

    return response


async def handle_json_rpc_request(
    app: FastMCP, request: Dict[str, Any]
) -> Dict[str, Any]:
    """Handle a JSON-RPC 2.0 request"""
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})

    logger.debug(f"[RPC] Handling {method} with params: {params}")

    try:
        if method == "initialize":
            # Handle MCP initialize request
            logger.debug("[RPC] Processing initialize request")
            return create_json_rpc_response(
                request_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {},
                    },
                    "serverInfo": {
                        "name": "garmin-mcp-server",
                        "version": "1.0.0",
                    },
                },
            )

        elif method == "tools/list":
            # Import here to avoid circular dependency
            from garmin_mcp import get_whitelisted_tools
            tools = await get_whitelisted_tools(app)
            return create_json_rpc_response(request_id, {"tools": tools})

        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})

            logger.debug(f"[RPC] Calling tool: {tool_name} with args: {tool_args}")

            try:
                raw_result = await app.call_tool(tool_name, tool_args)

                # Normalize tool result to MCP-compatible shape: { content: [ { type: 'text', text: ... } ] }
                # If the tool already returned a dict with a 'content' array, keep it.
                if (
                    isinstance(raw_result, dict)
                    and "content" in raw_result
                    and isinstance(raw_result["content"], list)
                ):
                    normalized = raw_result
                else:
                    # Convert non-string results to pretty JSON string
                    if not isinstance(raw_result, str):
                        try:
                            pretty = json.dumps(raw_result, indent=2, ensure_ascii=False)
                        except Exception:
                            pretty = str(raw_result)
                    else:
                        pretty = raw_result

                    normalized = {
                        "content": [
                            {
                                "type": "text",
                                "text": pretty,
                            }
                        ]
                    }

                return create_json_rpc_response(request_id, normalized)
            except Exception as e:
                logger.error(f"Tool execution error: {str(e)}")
                return create_json_rpc_response(
                    request_id,
                    None,
                    {
                        "code": -32603,
                        "message": f"Internal error: {str(e)}",
                    },
                )

        else:
            return create_json_rpc_response(
                request_id,
                None,
                {
                    "code": -32601,
                    "message": f"Method not found: {method}",
                },
            )

    except Exception as e:
        logger.error(f"Unexpected error handling request: {str(e)}")
        return create_json_rpc_response(
            request_id,
            None,
            {
                "code": -32603,
                "message": f"Internal server error: {str(e)}",
            },
        )


async def start_websocket_server(app: FastMCP, port: int = 5001):
    """Start WebSocket server with HTTP endpoints"""
    try:
        import uvicorn
        from fastapi import FastAPI, WebSocket
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import JSONResponse

        # Create FastAPI app for HTTP/WebSocket
        fastapi_app = FastAPI(title="Garmin MCP Server")

        # Add CORS middleware
        fastapi_app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Health check endpoint
        @fastapi_app.get("/health")
        async def health():
            return {"status": "ok", "version": "1.0.0"}

        @fastapi_app.get("/")
        async def root():
            return {"message": "Garmin MCP Server", "mode": "websocket"}

        # List tools endpoint
        @fastapi_app.get("/listTools")
        async def list_tools():
            try:
                from garmin_mcp import get_whitelisted_tools
                tools = await get_whitelisted_tools(app)
                return JSONResponse({"tools": tools})
            except Exception as e:
                logger.error(f"Error listing tools: {str(e)}")
                return JSONResponse(
                    {"error": f"Failed to list tools: {str(e)}"}, status_code=500
                )

        # JSON-RPC HTTP endpoint
        @fastapi_app.post("/rpc")
        @fastapi_app.post("/")
        async def rpc_handler(request: Dict[str, Any]):
            try:
                return await handle_json_rpc_request(app, request)
            except Exception as e:
                logger.error(f"RPC error: {str(e)}")
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32700,
                            "message": f"Parse error: {str(e)}",
                        },
                    },
                    status_code=400,
                )

        # WebSocket endpoint
        @fastapi_app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket):
            await websocket.accept()
            logger.debug("WebSocket client connected")

            try:
                while True:
                    data = await websocket.receive_text()
                    logger.debug(f"Received: {data}")

                    try:
                        request = json.loads(data)
                        response = await handle_json_rpc_request(app, request)
                        await websocket.send_json(response)
                    except json.JSONDecodeError as e:
                        await websocket.send_json(
                            {
                                "jsonrpc": "2.0",
                                "error": {
                                    "code": -32700,
                                    "message": f"Parse error: {str(e)}",
                                },
                            }
                        )

            except Exception as e:
                logger.error(f"WebSocket error: {str(e)}")
            finally:
                await websocket.close()

        logger.info(f"Starting WebSocket server on port {port}...")

        config = uvicorn.Config(
            fastapi_app,
            host="0.0.0.0",
            port=port,
            log_level="debug",
            access_log=True,
        )
        server = uvicorn.Server(config)
        await server.serve()

    except ImportError:
        logger.error(
            "FastAPI or uvicorn not installed. Install with: pip install fastapi uvicorn"
        )
        sys.exit(1)


def run_websocket_mode(app: FastMCP, port: int = 5001):
    """Run the server in WebSocket mode (async wrapper)"""
    logger.info("[DEBUG] Starting in WebSocket mode...")
    asyncio.run(start_websocket_server(app, port))
