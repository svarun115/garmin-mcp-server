"""
HTTP Adapter for Garmin MCP Server - Proxies to WebSocket backend
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict
from datetime import datetime

import aiohttp

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="[%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("garmin-adapter")

HTTP_PORT = int(os.getenv("PORT", "5000"))
WS_BACKEND_URL = os.getenv("WS_BACKEND_URL", "ws://localhost:5001")

# Tool cache
tool_cache: Dict[str, Any] = {"tools": [], "timestamp": 0, "backend_connected": False}
CACHE_TTL = 60  # 60 seconds


async def check_backend_connection():
    """Check if WebSocket backend is running"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{WS_BACKEND_URL.replace('ws://', 'http://')}") as resp:
                tool_cache["backend_connected"] = resp.status == 200
                logger.debug(f"Backend health check: {resp.status}")
    except Exception as e:
        tool_cache["backend_connected"] = False
        logger.warning(f"Backend connection failed: {str(e)}")


async def fetch_tools_from_backend():
    """Fetch tools from WebSocket backend"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{WS_BACKEND_URL.replace('ws://', 'http://')}/listTools"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    tool_cache["tools"] = data.get("tools", [])
                    tool_cache["timestamp"] = datetime.now().timestamp()
                    tool_cache["backend_connected"] = True
                    logger.debug(f"Fetched {len(tool_cache['tools'])} tools from backend")
                    return tool_cache["tools"]
                else:
                    logger.error(f"Failed to fetch tools: HTTP {resp.status}")
    except Exception as e:
        logger.error(f"Error fetching tools: {str(e)}")

    return tool_cache["tools"]


async def get_tools():
    """Get tools with caching"""
    now = datetime.now().timestamp()

    # Check if cache is valid
    if (
        tool_cache["tools"]
        and (now - tool_cache["timestamp"]) < CACHE_TTL
        and tool_cache["backend_connected"]
    ):
        logger.debug("Using cached tools")
        return tool_cache["tools"]

    # Cache miss or expired - fetch fresh tools
    logger.debug("Fetching fresh tools from backend")
    return await fetch_tools_from_backend()


async def proxy_rpc_request(request: Dict[str, Any]) -> Dict[str, Any]:
    """Proxy a JSON-RPC request to the WebSocket backend via HTTP endpoint"""
    try:
        async with aiohttp.ClientSession() as session:
            # Connect to backend via HTTP /rpc endpoint (not WebSocket)
            backend_http_url = WS_BACKEND_URL.replace('ws://', 'http://').replace('wss://', 'https://')
            url = f"{backend_http_url}/rpc"
            
            async with session.post(
                url,
                json=request,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status == 200:
                    response = await resp.json()
                    logger.debug(f"Received response from backend: {response}")
                    return response
                else:
                    logger.error(f"Backend HTTP error: {resp.status}")
                    return {
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32603,
                            "message": f"Backend HTTP error: {resp.status}",
                        },
                    }

    except asyncio.TimeoutError:
        logger.error("Backend request timeout")
        return {
            "jsonrpc": "2.0",
            "error": {
                "code": -32603,
                "message": "Backend request timeout",
            },
        }
    except Exception as e:
        logger.error(f"Error proxying request: {str(e)}")
        return {
            "jsonrpc": "2.0",
            "error": {
                "code": -32603,
                "message": f"Backend error: {str(e)}",
            },
        }


async def start_http_adapter():
    """Start HTTP adapter server"""
    try:
        from fastapi import FastAPI, Request
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import JSONResponse
        import uvicorn

        # Create FastAPI app
        app = FastAPI(title="Garmin MCP HTTP Adapter")

        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Health check endpoint
        @app.get("/health")
        async def health():
            return {"status": "ok", "version": "1.0.0"}

        # Status endpoint
        @app.get("/status")
        async def status():
            await check_backend_connection()
            return {
                "adapter": "running",
                "backend_connected": tool_cache["backend_connected"],
                "backend_url": WS_BACKEND_URL,
                "tools_cached": len(tool_cache["tools"]),
                "cache_age_seconds": datetime.now().timestamp()
                - tool_cache["timestamp"],
            }

        # Root endpoint
        @app.get("/")
        async def root():
            return {
                "message": "Garmin MCP HTTP Adapter",
                "backend_url": WS_BACKEND_URL,
            }

        # List tools endpoint
        @app.get("/listTools")
        async def list_tools():
            try:
                tools = await get_tools()
                return JSONResponse({"tools": tools})
            except Exception as e:
                logger.error(f"Error listing tools: {str(e)}")
                return JSONResponse(
                    {"error": f"Failed to list tools: {str(e)}"}, status_code=500
                )

        # JSON-RPC HTTP endpoint
        @app.post("/rpc")
        @app.post("/")
        async def rpc_handler(request: Request):
            try:
                body = await request.json()
                response = await proxy_rpc_request(body)
                return JSONResponse(response)
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

        # WebSocket upgrade endpoint
        @app.websocket("/ws")
        async def websocket_endpoint(websocket):
            from fastapi import WebSocket

            await websocket.accept()
            logger.debug("WebSocket client connected to adapter")

            try:
                while True:
                    data = await websocket.receive_text()
                    logger.debug(f"Received from client: {data}")

                    try:
                        request = json.loads(data)
                        response = await proxy_rpc_request(request)
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

        logger.info(f"Starting HTTP Adapter on port {HTTP_PORT}...")
        logger.info(f"Backend WebSocket URL: {WS_BACKEND_URL}")

        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=HTTP_PORT,
            log_level="debug",
            access_log=True,
        )
        server = uvicorn.Server(config)
        await server.serve()

    except ImportError:
        logger.error(
            "FastAPI or uvicorn not installed. Install with: pip install fastapi uvicorn aiohttp"
        )
        sys.exit(1)


def run_http_adapter():
    """Run the HTTP adapter (async wrapper)"""
    logger.info("[DEBUG] Starting HTTP Adapter...")
    asyncio.run(start_http_adapter())


if __name__ == "__main__":
    run_http_adapter()
