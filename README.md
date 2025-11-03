[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/taxuspt-garmin-mcp-badge.png)](https://mseep.ai/app/taxuspt-garmin-mcp)

# Garmin MCP Server

This Model Context Protocol (MCP) server connects to Garmin Connect and exposes your fitness and health data to Claude and other MCP-compatible clients.

## Features

- List recent activities
- Get detailed activity information
- Access health metrics (steps, heart rate, sleep)
- View body composition data

## Setup

1. Install the required packages on a new environment:

```bash
uv sync
```

## Running the Server

The Garmin MCP server now supports three deployment modes:

### Mode 1: WebSocket (Default, Recommended)

```bash
# Terminal 1: Start WebSocket backend
PORT=5001 uv run garmin-mcp

# Terminal 2 (Optional): Start HTTP adapter for testing
PORT=5000 WS_BACKEND_URL=ws://localhost:5001 python -m garmin_mcp.http_adapter
```

**Features:**
- Fast, bidirectional communication
- HTTP endpoints for testing with curl
- Supports remote access with HTTP adapter
- JSON-RPC 2.0 protocol

**Claude Desktop Configuration (WebSocket):**
```json
{
  "mcpServers": {
    "garmin": {
      "command": "uvx",
      "args": ["--python", "3.12", "--from", "git+https://github.com/Taxuspt/garmin_mcp", "garmin-mcp"],
      "env": {
        "GARMIN_EMAIL": "YOUR_GARMIN_EMAIL",
        "GARMIN_PASSWORD": "YOUR_GARMIN_PASSWORD",
        "PORT": "5001"
      }
    }
  }
}
```

### Mode 2: Stdio (Original, Direct Integration)

```bash
uv run garmin-mcp --stdio
```

**Features:**
- Direct client integration
- No additional processes needed
- Original behavior preserved
- Fully backward compatible

**Claude Desktop Configuration (Stdio):**
```json
{
  "mcpServers": {
    "garmin": {
      "command": "uvx",
      "args": [
        "--python",
        "3.12",
        "--from",
        "git+https://github.com/Taxuspt/garmin_mcp",
        "garmin-mcp",
        "--stdio"
      ],
      "env": {
        "GARMIN_EMAIL": "YOUR_GARMIN_EMAIL",
        "GARMIN_PASSWORD": "YOUR_GARMIN_PASSWORD"
      }
    }
  }
}
```

### Mode 3: HTTP Adapter (For Testing & Remote Access)

```bash
# Terminal 1: Start WebSocket backend
PORT=5001 uv run garmin-mcp

# Terminal 2: Start HTTP adapter (requires backend running)
PORT=5000 WS_BACKEND_URL=ws://localhost:5001 python -m garmin_mcp.http_adapter
```

**Features:**
- HTTP endpoints for easy testing
- Tool caching
- Can run on separate machine from backend
- Perfect for development and debugging

**Test with curl:**
```bash
# Health check
curl http://localhost:5001/health

# List tools
curl http://localhost:5000/listTools

# Call a tool
curl -X POST http://localhost:5000/rpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## Mode Comparison

| Feature | WebSocket | Stdio | HTTP Adapter |
|---------|-----------|-------|--------------|
| Protocol | JSON-RPC 2.0 | MCP Stdio | HTTP/JSON-RPC |
| Port | 5001 (default) | N/A | 5000 (default) |
| Performance | Fast | Good | Moderate |
| Remote Access | Yes (with proxy) | No | Yes |
| Claude Desktop | ✓ | ✓ (--stdio) | ✓ (proxied) |
| Testing | curl | stdio | curl |

## Configuration

### Environment Variables

```bash
GARMIN_EMAIL="your_email"              # Required
GARMIN_PASSWORD="your_password"        # Required
PORT="5001"                            # Optional (default: 5001 for WebSocket, 5000 for adapter)
WS_BACKEND_URL="ws://localhost:5001"  # Optional (adapter only)
```

### With Claude Desktop

Edit your configuration file and set the `PORT` environment variable:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

## Usage Examples

Once connected in Claude, you can ask questions like:

- "Show me my recent activities"
- "What was my sleep like last night?"
- "How many steps did I take yesterday?"
- "Show me the details of my latest run"

## Security Note

## Troubleshooting

### Port Already in Use

If port is already in use, kill the existing process or use a different port:

```bash
# Use a different port
PORT=5002 uv run garmin-mcp
```

### WebSocket Connection Issues

- Ensure firewall allows WebSocket connections
- Check backend is running: `curl http://localhost:5001/health`
- Verify `WS_BACKEND_URL` environment variable is set correctly

### Claude Desktop Not Finding Server

1. Verify credentials (GARMIN_EMAIL, GARMIN_PASSWORD)
2. Check the correct mode is specified (with or without --stdio)
3. Restart Claude Desktop completely
4. Check Claude Desktop logs:
   - macOS: `~/Library/Logs/Claude/mcp-server-garmin.log`
   - Windows: `%APPDATA%\Claude\logs\mcp-server-garmin.log`

### Login Issues

1. Verify your Garmin Connect credentials
2. Check if Garmin requires additional verification
3. Clear token cache: `rm -rf ~/.garminconnect ~/.garminconnect_base64`
4. Try logging in again

### HTTP Adapter Not Connecting to Backend

```bash
# Verify backend is running
curl http://localhost:5001/health

# Check adapter status
curl http://localhost:5000/status
```
