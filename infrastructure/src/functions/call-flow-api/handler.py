"""
Query API Lambda for Call Flow Visualizer.

Serves REST API endpoints for listing calls, viewing call timelines,
and searching by tool usage or disposition.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any

import boto3
import structlog
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger(__name__)

EVENTS_TABLE_NAME = os.environ["EVENTS_TABLE_NAME"]
SESSION_TABLE_NAME = os.environ["SESSION_TABLE_NAME"]

dynamodb = boto3.resource("dynamodb")
events_table = dynamodb.Table(EVENTS_TABLE_NAME)
sessions_table = dynamodb.Table(SESSION_TABLE_NAME)


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types from DynamoDB."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            if obj % 1 == 0:
                return int(obj)
            return float(obj)
        return super().default(obj)


def _json_response(status_code: int, body: Any) -> dict[str, Any]:
    """Build an API Gateway proxy response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def _get_session_metadata(session_id: str) -> dict[str, Any] | None:
    """Fetch session metadata from the sessions table."""
    if not session_id:
        return None
    try:
        response = sessions_table.get_item(
            Key={"PK": f"SESSION#{session_id}", "SK": "METADATA"},
            ConsistentRead=False,
        )
        return response.get("Item")
    except ClientError as e:
        logger.warning(
            "session_lookup_failed",
            session_id=session_id,
            error=str(e),
        )
        return None


def _handle_list_calls(params: dict[str, str]) -> dict[str, Any]:
    """GET /api/calls -- list calls by date range.

    Merges session_ended + call_metrics_summary into one entry per call.
    Returns enriched objects with duration, turns, avg_response_ms, status.

    Supports multi-day queries via `days_back` parameter (default 1, max 30).
    If `date_from` is provided, it takes precedence as a single-day query.
    """
    from datetime import datetime, timedelta, timezone

    date_from = params.get("date_from", "")
    days_back = min(int(params.get("days_back", "1")), 30)
    disposition = params.get("disposition", "")
    limit = min(int(params.get("limit", "50")), 100)
    next_token = params.get("next_token")

    # Build list of dates to query
    if date_from:
        # Explicit date_from: single-day query (backward compatible)
        dates = [date_from]
    else:
        today = datetime.now(tz=timezone.utc).date()
        dates = [(today - timedelta(days=i)).isoformat() for i in range(days_back)]

    # Query each date partition and collect items
    all_items: list[dict[str, Any]] = []
    last_key = None

    for date_str in dates:
        query_kwargs: dict[str, Any] = {
            "IndexName": "GSI1",
            "KeyConditionExpression": Key("GSI1PK").eq(f"DATE#{date_str}"),
            "Limit": limit * 2,  # fetch extra to account for dedup
            "ScanIndexForward": False,
        }

        if disposition:
            query_kwargs["KeyConditionExpression"] &= Key("GSI1SK").begins_with(
                f"DISP#{disposition}#"
            )

        # Only apply pagination token on the first date (for backward compat)
        if next_token and date_str == dates[0]:
            query_kwargs["ExclusiveStartKey"] = json.loads(next_token)

        response = events_table.query(**query_kwargs)
        all_items.extend(response.get("Items", []))

        # Track last evaluated key from the final date partition
        if response.get("LastEvaluatedKey"):
            last_key = response["LastEvaluatedKey"]

    # Deduplicate: merge session_ended + call_metrics_summary by call_id
    calls_map: dict[str, dict[str, Any]] = {}
    for item in all_items:
        cid = item.get("call_id", "")
        if not cid:
            continue
        if cid not in calls_map:
            calls_map[cid] = {
                "call_id": cid,
                "session_id": item.get("session_id", ""),
                "timestamp": item.get("timestamp", ""),
            }
        entry = calls_map[cid]
        data = item.get("data", {})

        if item.get("event_type") == "session_ended":
            entry["status"] = data.get("end_status", "unknown")
            entry["turn_count"] = data.get("turn_count")
            # Use session_ended timestamp as the canonical time
            entry["timestamp"] = item.get("timestamp", entry.get("timestamp", ""))
        elif item.get("event_type") == "call_metrics_summary":
            entry["duration_seconds"] = data.get("duration_seconds")
            entry["turn_count"] = entry.get("turn_count") or data.get("turn_count")
            entry["avg_response_ms"] = data.get("avg_agent_response_ms")
            entry["avg_rms_db"] = data.get("avg_rms_db")
            entry["poor_audio_turns"] = data.get("poor_audio_turns")
            entry["interruption_count"] = data.get("interruption_count")
            entry.setdefault("status", data.get("completion_status", "unknown"))

    calls = list(calls_map.values())[:limit]

    result: dict[str, Any] = {"calls": calls, "count": len(calls)}
    if last_key and len(dates) == 1:
        # Only return pagination token for single-date queries
        result["next_token"] = json.dumps(last_key, cls=DecimalEncoder)

    return _json_response(200, result)


def _handle_get_timeline(call_id: str) -> dict[str, Any]:
    """GET /api/calls/{call_id} -- get full call timeline.

    Derives summary fields (started_at, ended_at, duration, status, etc.)
    directly from the ingested events so the response is self-contained.
    """
    response = events_table.query(
        KeyConditionExpression=Key("PK").eq(f"CALL#{call_id}")
        & Key("SK").begins_with("TS#"),
        ScanIndexForward=True,
    )
    events = response.get("Items", [])

    if not events:
        return _json_response(404, {"error": "Call not found", "call_id": call_id})

    # Derive summary from events themselves
    session_id = ""
    started_at = ""
    ended_at = ""
    end_status = ""
    turn_count = None
    duration_seconds = None
    metrics: dict[str, Any] = {}

    for evt in events:
        if evt.get("session_id") and not session_id:
            session_id = evt["session_id"]

        etype = evt.get("event_type", "")
        data = evt.get("data", {})

        if etype == "session_started":
            started_at = evt.get("timestamp", "")
        elif etype == "session_ended":
            ended_at = evt.get("timestamp", "")
            end_status = data.get("end_status", "unknown")
            turn_count = turn_count or data.get("turn_count")
        elif etype == "call_metrics_summary":
            duration_seconds = data.get("duration_seconds")
            turn_count = turn_count or data.get("turn_count")
            metrics = data

    result: dict[str, Any] = {
        "call_id": call_id,
        "session_id": session_id,
        "event_count": len(events),
        "events": events,
        "started_at": started_at,
        "ended_at": ended_at,
        "end_status": end_status,
        "turn_count": turn_count,
        "duration_seconds": duration_seconds,
        "metrics": metrics,
    }

    return _json_response(200, result)


def _handle_get_summary(call_id: str) -> dict[str, Any]:
    """GET /api/calls/{call_id}/summary -- get call summary."""
    # Fetch call_metrics_summary event if it exists
    response = events_table.query(
        KeyConditionExpression=Key("PK").eq(f"CALL#{call_id}")
        & Key("SK").begins_with("TS#"),
        ScanIndexForward=True,
    )
    events = response.get("Items", [])

    if not events:
        return _json_response(404, {"error": "Call not found", "call_id": call_id})

    summary_event = None
    session_id = ""
    for evt in events:
        if evt.get("session_id"):
            session_id = evt["session_id"]
        if evt.get("event_type") == "call_metrics_summary":
            summary_event = evt

    session = _get_session_metadata(session_id)

    result: dict[str, Any] = {
        "call_id": call_id,
        "session_id": session_id,
        "event_count": len(events),
    }

    if summary_event:
        result["metrics"] = summary_event.get("data", {})

    if session:
        result["started_at"] = session.get("started_at")
        result["ended_at"] = session.get("ended_at")
        result["end_status"] = session.get("end_status")
        result["turn_count"] = session.get("turn_count")

    return _json_response(200, result)


def _handle_search(params: dict[str, str]) -> dict[str, Any]:
    """GET /api/search -- search by tool name, disposition, or call_id."""
    tool_name = params.get("tool_name", "")
    call_id = params.get("call_id", "")
    date = params.get("date", "")
    limit = min(int(params.get("limit", "50")), 100)

    if call_id:
        # Direct lookup by call_id
        return _handle_get_timeline(call_id)

    if tool_name:
        query_kwargs: dict[str, Any] = {
            "IndexName": "GSI2",
            "KeyConditionExpression": Key("GSI2PK").eq(f"TOOL#{tool_name}"),
            "Limit": limit,
            "ScanIndexForward": False,
        }
        if date:
            query_kwargs["KeyConditionExpression"] &= Key("GSI2SK").begins_with(
                f"DATE#{date}#"
            )
        response = events_table.query(**query_kwargs)
        return _json_response(
            200,
            {
                "results": response.get("Items", []),
                "count": response.get("Count", 0),
            },
        )

    return _json_response(400, {"error": "Provide tool_name or call_id parameter"})


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for API Gateway proxy integration."""
    http_method = event.get("httpMethod", "GET")
    path = event.get("path", "")
    params = event.get("queryStringParameters") or {}
    path_params = event.get("pathParameters") or {}

    logger.info("api_request", method=http_method, path=path)

    # Handle CORS preflight
    if http_method == "OPTIONS":
        return _json_response(200, {})

    try:
        # Route: GET /api/calls
        if path == "/api/calls" and http_method == "GET":
            return _handle_list_calls(params)

        # Route: GET /api/calls/{call_id}/summary
        if path.endswith("/summary") and http_method == "GET":
            call_id = path_params.get("call_id", path.split("/")[-2])
            return _handle_get_summary(call_id)

        # Route: GET /api/calls/{call_id}
        if path.startswith("/api/calls/") and http_method == "GET":
            call_id = path_params.get("call_id", path.split("/")[-1])
            return _handle_get_timeline(call_id)

        # Route: GET /api/search
        if path == "/api/search" and http_method == "GET":
            return _handle_search(params)

        return _json_response(404, {"error": "Not found", "path": path})

    except Exception as e:
        logger.error("api_error", error=str(e), error_type=type(e).__name__, path=path)
        return _json_response(500, {"error": "Internal server error"})
