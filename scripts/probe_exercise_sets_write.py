"""Probe Garmin's exerciseSets write endpoint empirically.

Run this once locally to verify the PUT contract before exposing
update_activity_exercise_sets through the MCP server.

Usage:
    cd ~/Assistant/mcp-servers/garmin-mcp-server
    cp .env.example .env  # then fill in GARMIN_EMAIL / GARMIN_PASSWORD
    uv run python scripts/probe_exercise_sets_write.py <activity_id>

Strategy:
    1. GET  /activity-service/activity/<id>/exerciseSets  -> capture current payload
    2. PUT  the same payload back unchanged                -> see if endpoint accepts it
    3. PUT  with one cosmetic change (e.g., notes)         -> see if change persists

Stops after a successful no-op PUT. The point is to confirm the URL +
HTTP verb + payload shape — not to mutate real data.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from garminconnect import Garmin


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: probe_exercise_sets_write.py <activity_id>")
        return 2

    activity_id = sys.argv[1]
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    email = os.environ["GARMIN_EMAIL"]
    password = os.environ["GARMIN_PASSWORD"]

    token_dir = Path.home() / ".garminconnect"
    g = Garmin(email, password)
    if token_dir.exists() and any(token_dir.iterdir()):
        try:
            g.login(str(token_dir))
            print(f"(reused cached tokens at {token_dir})")
        except Exception as e:
            print(f"(cached login failed: {e}; falling back to fresh login)")
            g.login()
            g.garth.dump(str(token_dir))
    else:
        g.login()
        token_dir.mkdir(exist_ok=True)
        g.garth.dump(str(token_dir))
        print(f"(cached tokens to {token_dir})")

    print(f"--- step 1: GET exerciseSets for activity {activity_id} ---")
    current = g.get_activity_exercise_sets(activity_id)
    print(json.dumps(current, indent=2)[:2000])
    print(f"(payload length: {len(json.dumps(current))} chars)")

    print(f"\n--- step 2: PUT same payload back unchanged ---")
    url = f"/activity-service/activity/{activity_id}/exerciseSets"
    try:
        resp = g.garth.put("connectapi", url, json=current, api=True)
        print(f"status_code: {getattr(resp, 'status_code', '?')}")
        body = None
        try:
            body = resp.json()
        except Exception:
            body = getattr(resp, "text", None)
        print(f"body: {body!r}")
        print("\n✅ PUT accepted. Endpoint contract: PUT", url)
        print("   payload shape: same as GET response.")
    except Exception as e:
        print(f"❌ PUT failed: {type(e).__name__}: {e}")
        print("\nTry alternate shapes:")
        print("  - just the inner array under 'exerciseSets' key")
        print("  - per-set PUT to /exerciseSets/<index>")
        print("  - POST instead of PUT")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
