"""
JSON-RPC 2.0 validation and utility functions for MCP.

Handles:
- Request/notification validation
- Error code constants
- Response formatting
"""

from typing import Any, Optional


# JSON-RPC 2.0 Error Codes
class JsonRpcError:
    """Standard JSON-RPC 2.0 error codes"""
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


def is_valid_jsonrpc(data: dict) -> bool:
    """
    Validate basic JSON-RPC 2.0 structure.
    
    Args:
        data: Parsed JSON object
        
    Returns:
        True if valid JSON-RPC request/notification
    """
    if not isinstance(data, dict):
        return False
    
    # Must have jsonrpc version
    if data.get("jsonrpc") != "2.0":
        return False
    
    # Must have method
    if "method" not in data or not isinstance(data["method"], str):
        return False
    
    return True


def is_notification(data: dict) -> bool:
    """
    Check if JSON-RPC message is a notification (no response expected).
    
    Args:
        data: JSON-RPC message
        
    Returns:
        True if notification (no "id" field)
    """
    return "id" not in data


def create_success_response(request_id: Any, result: Any) -> dict:
    """
    Create a JSON-RPC success response.
    
    Args:
        request_id: ID from original request
        result: Result data
        
    Returns:
        JSON-RPC response object
    """
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result
    }


def create_error_response(request_id: Any, code: int, message: str, data: Any = None) -> dict:
    """
    Create a JSON-RPC error response.
    
    Args:
        request_id: ID from original request (can be None)
        code: Error code
        message: Error message
        data: Optional additional error data
        
    Returns:
        JSON-RPC error response object
    """
    error = {
        "code": code,
        "message": message
    }
    
    if data is not None:
        error["data"] = data
    
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": error
    }


def validate_mcp_protocol_version(version: Optional[str]) -> bool:
    """
    Validate MCP-Protocol-Version header.
    
    Args:
        version: Protocol version string (e.g., "2024-11-05")
        
    Returns:
        True if supported version
    """
    if not version:
        return False
    
    # Currently support 2024-11-05
    supported_versions = ["2024-11-05"]
    return version in supported_versions
