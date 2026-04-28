"""
Activity Management functions for Garmin Connect MCP Server
"""
import datetime
import json
from typing import Any, Dict, List, Optional, Union

# The garmin_client will be set by the main file
garmin_client = None

# Fields to include in slim/summary mode for get_activities_by_date
_SUMMARY_FIELDS = [
    "activityId", "activityName", "activityType",
    "startTimeLocal", "startTimeGMT",
    "duration", "elapsedDuration", "movingDuration",
    "distance", "elevationGain", "elevationLoss",
    "averageSpeed", "maxSpeed",
    "averageHR", "maxHR", "calories",
    "startLatitude", "startLongitude",
    "endLatitude", "endLongitude",
    "locationName",
    "hasPolyline",
    "sportTypeId",
]


def _slim_activity(activity: dict) -> dict:
    """Extract summary fields from a full activity record."""
    slim = {}
    for key in _SUMMARY_FIELDS:
        if key in activity:
            slim[key] = activity[key]
    # Also pull typeKey from nested activityType if present
    at = activity.get("activityType")
    if isinstance(at, dict):
        slim["typeKey"] = at.get("typeKey")
    return slim


def configure(client):
    """Configure the module with the Garmin client instance"""
    global garmin_client
    garmin_client = client


def register_tools(app):
    """Register all activity management tools with the MCP server app"""
    
    @app.tool()
    async def get_activities_by_date(
        start_date: str,
        end_date: str,
        activity_type: str = "",
        summary: bool = True,
    ) -> str:
        """Get activities data between specified dates, optionally filtered by activity type
        
        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            activity_type: Optional activity type filter (e.g., cycling, running, swimming)
            summary: If true (default), return slim per-activity records to avoid token
                overflow. Includes: activityId, activityName, typeKey, startTimeLocal,
                duration, distance, locationName, GPS coords, hasPolyline.
                Set to false for the full Garmin response.
        """
        try:
            activities = garmin_client.get_activities_by_date(start_date, end_date, activity_type)
            if not activities:
                return f"No activities found between {start_date} and {end_date}" + \
                       (f" for activity type '{activity_type}'" if activity_type else "")
            
            if summary:
                activities = [_slim_activity(a) for a in activities]

            return json.dumps(activities)
        except Exception as e:
            return f"Error retrieving activities by date: {str(e)}"

    @app.tool()
    async def get_activities_fordate(date: str) -> str:
        """Get activities for a specific date
        
        Args:
            date: Date in YYYY-MM-DD format
        """
        try:
            activities = garmin_client.get_activities_fordate(date)
            if not activities:
                return f"No activities found for {date}"
            
            return json.dumps(activities)
        except Exception as e:
            return f"Error retrieving activities for date: {str(e)}"

    @app.tool()
    async def get_activity(activity_id: int) -> str:
        """Get basic activity information
        
        Args:
            activity_id: ID of the activity to retrieve
        """
        try:
            activity = garmin_client.get_activity(activity_id)
            if not activity:
                return f"No activity found with ID {activity_id}"
            
            return json.dumps(activity)
        except Exception as e:
            return f"Error retrieving activity: {str(e)}"

    @app.tool()
    async def get_activity_gps_track(activity_id: int, max_points: int = 100) -> str:
        """Get the GPS polyline / track points for an activity.

        Returns a decimated list of {lat, lon, altitude, timestamp} points.
        Only available for outdoor activities with GPS (hasPolyline=true).

        Args:
            activity_id: ID of the activity to retrieve the GPS track for
            max_points: Maximum number of polyline points to return (default 100).
                Garmin records 1 point/sec so a 30-min run has ~1800 raw points.
                Lower values = smaller response, coarser track.
        """
        try:
            details = garmin_client.get_activity_details(
                activity_id, maxchart=100, maxpoly=max_points
            )
            if not details:
                return f"No details found for activity {activity_id}"

            # Extract the polyline from the geoPolylineDTO
            geo = details.get("geoPolylineDTO")
            if not geo or not geo.get("polyline"):
                return json.dumps({
                    "activity_id": activity_id,
                    "track": [],
                    "message": "No GPS track available for this activity"
                })

            polyline = geo["polyline"]
            track = []
            for pt in polyline:
                track.append({
                    "lat": pt.get("lat"),
                    "lon": pt.get("lon"),
                    "altitude": pt.get("altitude"),
                    "timestamp": pt.get("time"),
                })

            return json.dumps({
                "activity_id": activity_id,
                "point_count": len(track),
                "track": track,
            })
        except Exception as e:
            return f"Error retrieving GPS track: {str(e)}"

    @app.tool()
    async def get_activities_bulk(activity_ids: List[int]) -> str:
        """Get full activity details for multiple activities in one call.

        Equivalent to calling get_activity for each ID, but batched into a
        single tool response. Useful when you need full detail for 5-20
        activities (e.g., after filtering a list call).

        Args:
            activity_ids: List of activity IDs to fetch (max 25 per call)
        """
        if len(activity_ids) > 25:
            return json.dumps({
                "error": "Maximum 25 activity IDs per call. Split into multiple calls."
            })

        results = []
        errors = []
        for aid in activity_ids:
            try:
                activity = garmin_client.get_activity(aid)
                if activity:
                    results.append(activity)
                else:
                    errors.append({"activity_id": aid, "error": "Not found"})
            except Exception as e:
                errors.append({"activity_id": aid, "error": str(e)})

        response = {"activities": results, "count": len(results)}
        if errors:
            response["errors"] = errors
        return json.dumps(response)

    @app.tool()
    async def get_activity_splits(activity_id: int) -> str:
        """Get splits for an activity
        
        Args:
            activity_id: ID of the activity to retrieve splits for
        """
        try:
            splits = garmin_client.get_activity_splits(activity_id)
            if not splits:
                return f"No splits found for activity with ID {activity_id}"
            
            return json.dumps(splits)
        except Exception as e:
            return f"Error retrieving activity splits: {str(e)}"

    @app.tool()
    async def get_activity_typed_splits(activity_id: int) -> str:
        """Get typed splits for an activity
        
        Args:
            activity_id: ID of the activity to retrieve typed splits for
        """
        try:
            typed_splits = garmin_client.get_activity_typed_splits(activity_id)
            if not typed_splits:
                return f"No typed splits found for activity with ID {activity_id}"
            
            return json.dumps(typed_splits)
        except Exception as e:
            return f"Error retrieving activity typed splits: {str(e)}"

    @app.tool()
    async def get_activity_split_summaries(activity_id: int) -> str:
        """Get split summaries for an activity
        
        Args:
            activity_id: ID of the activity to retrieve split summaries for
        """
        try:
            split_summaries = garmin_client.get_activity_split_summaries(activity_id)
            if not split_summaries:
                return f"No split summaries found for activity with ID {activity_id}"
            
            return json.dumps(split_summaries)
        except Exception as e:
            return f"Error retrieving activity split summaries: {str(e)}"

    @app.tool()
    async def get_activity_weather(activity_id: int) -> str:
        """Get weather data for an activity
        
        Args:
            activity_id: ID of the activity to retrieve weather data for
        """
        try:
            weather = garmin_client.get_activity_weather(activity_id)
            if not weather:
                return f"No weather data found for activity with ID {activity_id}"
            
            return json.dumps(weather)
        except Exception as e:
            return f"Error retrieving activity weather data: {str(e)}"

    @app.tool()
    async def get_activity_hr_in_timezones(activity_id: int) -> str:
        """Get heart rate data in different time zones for an activity
        
        Args:
            activity_id: ID of the activity to retrieve heart rate time zone data for
        """
        try:
            hr_zones = garmin_client.get_activity_hr_in_timezones(activity_id)
            if not hr_zones:
                return f"No heart rate time zone data found for activity with ID {activity_id}"
            
            return json.dumps(hr_zones)
        except Exception as e:
            return f"Error retrieving activity heart rate time zone data: {str(e)}"

    @app.tool()
    async def get_activity_gear(activity_id: int) -> str:
        """Get gear data used for an activity
        
        Args:
            activity_id: ID of the activity to retrieve gear data for
        """
        try:
            gear = garmin_client.get_activity_gear(activity_id)
            if not gear:
                return f"No gear data found for activity with ID {activity_id}"
            
            return json.dumps(gear)
        except Exception as e:
            return f"Error retrieving activity gear data: {str(e)}"

    @app.tool()
    async def get_activity_exercise_sets(activity_id: int) -> str:
        """Get exercise sets for strength training activities

        Args:
            activity_id: ID of the activity to retrieve exercise sets for
        """
        try:
            exercise_sets = garmin_client.get_activity_exercise_sets(activity_id)
            if not exercise_sets:
                return f"No exercise sets found for activity with ID {activity_id}"

            return json.dumps(exercise_sets)
        except Exception as e:
            return f"Error retrieving activity exercise sets: {str(e)}"

    @app.tool()
    async def update_activity_exercise_sets(activity_id: int, payload: Dict[str, Any]) -> str:
        """Update exercise sets on a strength training activity (correct auto-detected
        exercises, fix reps/weight, change set type).

        Treats Garmin as the source of truth for strength workout detail. Typical flow:
        fetch the current payload via get_activity_exercise_sets, edit it, submit it here.

        Args:
            activity_id: ID of the activity to update.
            payload: Full exerciseSets JSON (same shape returned by
                get_activity_exercise_sets). Must include the top-level "exerciseSets"
                array with each set's category, exerciseName, reps, weight, etc.
        """
        try:
            url = f"/activity-service/activity/{activity_id}/exerciseSets"
            resp = garmin_client.garth.put(
                "connectapi", url, json=payload, api=True
            )
            result = {
                "status_code": getattr(resp, "status_code", None),
                "body": _safe_json(resp),
                "activity_id": activity_id,
            }
            return json.dumps(result)
        except Exception as e:
            return f"Error updating activity exercise sets: {str(e)}"

    return app


def _safe_json(resp):
    """Best-effort JSON decode; fall back to text. Used by write tools."""
    try:
        return resp.json()
    except Exception:
        try:
            return resp.text
        except Exception:
            return None
