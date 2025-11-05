"""
SSE (Server-Sent Events) framing utilities for MCP Streamable HTTP transport.

According to MCP spec:
- Each SSE event is one or more "data:" lines followed by blank line
- Each data line contains a JSON-RPC message
- Multiple data lines for same event if JSON is split
"""

import json
from typing import Any


def format_sse_event(data: dict[str, Any]) -> str:
    """
    Format a JSON-RPC message as an SSE event.
    
    Args:
        data: JSON-RPC message dict
        
    Returns:
        SSE-formatted string with data: prefix and blank line terminator
        
    Example:
        >>> format_sse_event({"jsonrpc": "2.0", "id": "1", "result": {}})
        'data: {"jsonrpc":"2.0","id":"1","result":{}}\n\n'
    """
    json_str = json.dumps(data, separators=(',', ':'))
    return f"data: {json_str}\n\n"


def format_sse_error(error_id: str | int, code: int, message: str) -> str:
    """
    Format a JSON-RPC error as an SSE event.
    
    Args:
        error_id: Request ID from original request
        code: JSON-RPC error code
        message: Error message
        
    Returns:
        SSE-formatted error event
    """
    error_response = {
        "jsonrpc": "2.0",
        "id": error_id,
        "error": {
            "code": code,
            "message": message
        }
    }
    return format_sse_event(error_response)


async def sse_generator(messages: list[dict[str, Any]]):
    """
    Async generator for streaming multiple SSE events.
    
    Args:
        messages: List of JSON-RPC messages to stream
        
    Yields:
        SSE-formatted strings
        
    Usage:
        async for event in sse_generator([msg1, msg2, msg3]):
            # send event to client
    """
    for message in messages:
        yield format_sse_event(message)
