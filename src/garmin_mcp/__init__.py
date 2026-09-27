"""
Modular MCP Server for Garmin Connect Data
"""

import os

import requests
from mcp.server.fastmcp import FastMCP

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

# Whitelisted tools to expose via MCP (others remain internal)
WHITELISTED_TOOLS = {
    # Activity Management
    "get_activities_by_date",
    "get_activity",
    "get_activities_bulk",
    "get_activity_hr_in_timezones",
    "get_activity_splits",
    "get_activity_weather",
    "get_activity_exercise_sets",
    "get_activity_gps_track",
    "update_activity_exercise_sets",
    # Health & Wellness - Comprehensive daily summary
    "get_user_summary",  # Includes: steps, calories, heart rate, sleep, body battery, stress, wellness events
    # Health & Wellness - Detail (additive, not covered by user_summary)
    "get_sleep_data",           # Full sleep stage breakdown + sleep score
    "get_body_battery_events",  # What caused Body Battery changes (drain/recharge)
    # Training & Performance (Forerunner 165 supported)
    "get_hrv_data",             # Nightly HRV readings + 90-day baseline + status
    "get_max_metrics",          # VO2 max + fitness age
    "get_race_predictions",     # Predicted 5K/10K/HM/marathon times
    "get_training_effect",      # Aerobic/anaerobic training effect per activity
    # Goals & Records
    "get_personal_record",      # Personal records across activity types
    # Workouts
    "get_workout_by_id",
    "get_workouts",
}

# Import all modules
from garmin_mcp import activity_management
from garmin_mcp import health_wellness
from garmin_mcp import user_profile
from garmin_mcp import devices
from garmin_mcp import gear_management
from garmin_mcp import weight_management
from garmin_mcp import challenges
from garmin_mcp import training
from garmin_mcp import workouts
from garmin_mcp import data_management
from garmin_mcp import womens_health

def get_mfa() -> str:
    """Get MFA code from user input"""
    print("\nGarmin Connect MFA required. Please check your email/phone for the code.")
    return input("Enter MFA code: ")


async def get_whitelisted_tools(app):
    """Extract only whitelisted tools from the app for public exposure.
    
    All tool implementations remain in the app; this function returns
    only the whitelisted subset for listing in tools/list responses.
    
    Args:
        app: FastMCP app instance containing all tools
        
    Returns:
        List of tool definitions for exposed tools only
    """
    # Get all tools from the app (async)
    all_tools = await app.list_tools()
    
    # Convert Tool objects to dicts and filter to only whitelisted tools
    whitelisted = [
        {
            "name": tool.name,
            "description": tool.description or "",
            "inputSchema": tool.inputSchema,
        }
        for tool in all_tools
        if tool.name.lower() in {t.lower() for t in WHITELISTED_TOOLS}
    ]
    
    return whitelisted



# Get credentials from environment
email = os.environ.get("GARMIN_EMAIL")
password = os.environ.get("GARMIN_PASSWORD")
tokenstore = os.getenv("GARMINTOKENS") or "~/.garminconnect"
tokenstore_base64 = os.getenv("GARMINTOKENS_BASE64") or "~/.garminconnect_base64"


def init_api(email, password):
    """Initialize the Garmin client from the saved token store.

    garminconnect >= 0.3 keeps a single `garmin_tokens.json` (DI OAuth2) in
    the token store, refreshes the access token itself and re-saves the file,
    so a server started from valid tokens stays authenticated on its own.

    Deliberately no password login here: this runs unattended as a service,
    a first login may need an MFA code, and Garmin rate-limits cloud IPs. Tokens
    are minted by an interactive login elsewhere (see README) and copied in.
    If they are missing or rejected, fail loudly rather than start a server
    that answers every call with an auth error.
    """
    print(f"Logging in to Garmin Connect from token store '{tokenstore}'...")
    try:
        garmin = Garmin()
        garmin.login(tokenstore)
    except (
        FileNotFoundError,
        GarminConnectAuthenticationError,
        GarminConnectConnectionError,
        GarminConnectTooManyRequestsError,
        requests.exceptions.HTTPError,
    ) as err:
        print(
            f"Garmin login from token store failed: {type(err).__name__}: {err}\n"
            "Mint fresh tokens with an interactive login and copy garmin_tokens.json "
            f"into '{tokenstore}'."
        )
        return None
    return garmin


def create_app():
    """Create and configure the FastMCP app"""
    # Initialize Garmin client
    garmin_client = init_api(email, password)
    if not garmin_client:
        print("Failed to initialize Garmin Connect client. Exiting.")
        return None

    print("Garmin Connect client initialized successfully.")

    # Configure all modules with the Garmin client
    activity_management.configure(garmin_client)
    health_wellness.configure(garmin_client)
    user_profile.configure(garmin_client)
    devices.configure(garmin_client)
    gear_management.configure(garmin_client)
    weight_management.configure(garmin_client)
    challenges.configure(garmin_client)
    training.configure(garmin_client)
    workouts.configure(garmin_client)
    data_management.configure(garmin_client)
    womens_health.configure(garmin_client)

    # Create the MCP app
    app = FastMCP("Garmin Connect v1.0")

    # Register tools from all modules
    app = activity_management.register_tools(app)
    app = health_wellness.register_tools(app)
    app = user_profile.register_tools(app)
    app = devices.register_tools(app)
    app = gear_management.register_tools(app)
    app = weight_management.register_tools(app)
    app = challenges.register_tools(app)
    app = training.register_tools(app)
    app = workouts.register_tools(app)
    app = data_management.register_tools(app)
    app = womens_health.register_tools(app)

    # Add activity listing tool directly to the app
    @app.tool()
    async def list_activities(limit: int = 5) -> str:
        """List recent Garmin activities"""
        try:
            activities = garmin_client.get_activities(0, limit)

            if not activities:
                return "No activities found."

            result = f"Last {len(activities)} activities:\n\n"
            for idx, activity in enumerate(activities, 1):
                result += f"--- Activity {idx} ---\n"
                result += f"Activity: {activity.get('activityName', 'Unknown')}\n"
                result += (
                    f"Type: {activity.get('activityType', {}).get('typeKey', 'Unknown')}\n"
                )
                result += f"Date: {activity.get('startTimeLocal', 'Unknown')}\n"
                result += f"ID: {activity.get('activityId', 'Unknown')}\n\n"

            return result
        except Exception as e:
            return f"Error retrieving activities: {str(e)}"

    # Override list_tools to filter by whitelist
    original_list_tools = app.list_tools
    
    async def filtered_list_tools():
        """Return only whitelisted tools"""
        all_tools = await original_list_tools()
        whitelisted_tool_names = {name.lower() for name in WHITELISTED_TOOLS}
        filtered = [
            tool for tool in all_tools 
            if tool.name.lower() in whitelisted_tool_names
        ]
        return filtered
    
    app.list_tools = filtered_list_tools

    return app


def main():
    """Initialize the MCP server and run in selected mode"""
    import sys
    import argparse

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Garmin MCP Server")
    parser.add_argument('--stdio', action='store_true', help='Run in stdio mode (for Claude Desktop, VS Code)')
    parser.add_argument('--http', action='store_true', help='Run in HTTP mode (Streamable HTTP transport)')
    parser.add_argument('--port', type=int, default=5000, help='Port for HTTP mode (default: 5000)')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='Host for HTTP mode (default: 127.0.0.1)')
    
    args = parser.parse_args()

    # Create the app
    app = create_app()
    if not app:
        return

    if args.stdio:
        # Run in stdio mode
        print("[DEBUG] Starting in Stdio mode...", file=sys.stderr)
        app.run()
    elif args.http:
        # Run in HTTP mode (Streamable HTTP per MCP spec)
        from garmin_mcp.transport.http import run_http_server
        
        print(f"[DEBUG] Starting in HTTP mode (Streamable HTTP) on {args.host}:{args.port}/mcp...", file=sys.stderr)
        run_http_server(app, host=args.host, port=args.port)
    else:
        # Default: stdio mode for backward compatibility
        print("[DEBUG] Starting in Stdio mode (default)...", file=sys.stderr)
        app.run()


if __name__ == "__main__":
    main()
