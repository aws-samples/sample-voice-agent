"""
Event Ingester Lambda for Call Flow Visualizer.

Processes CloudWatch Logs subscription filter events and writes
normalized call events to the DynamoDB call events table.
"""

from __future__ import annotations

import base64
import gzip
import json
import os
import time
from decimal import Decimal
from typing import Any

import boto3
import structlog
from botocore.exceptions import ClientError

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger(__name__)

EVENTS_TABLE_NAME = os.environ["EVENTS_TABLE_NAME"]
EVENT_TTL_DAYS = int(os.environ.get("EVENT_TTL_DAYS", "30"))

SUPPORTED_EVENTS = frozenset(
    [
        "conversation_turn",
        "turn_completed",
        "tool_execution",
        "barge_in",
        "session_started",
        "session_ended",
        "a2a_tool_call_start",
        "a2a_tool_call_success",
        "a2a_tool_call_cache_hit",
        "a2a_tool_call_timeout",
        "a2a_tool_call_error",
        "call_metrics_summary",
        "audio_clipping_detected",
        "poor_audio_detected",
        "agent_transition",
        "flow_a2a_call_start",
        "flow_a2a_call_success",
        "flow_a2a_call_error",
        "flow_a2a_call_timeout",
    ]
)

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(EVENTS_TABLE_NAME)


def _sanitize_for_dynamodb(obj: Any) -> Any:
    """Recursively convert floats to Decimals and remove None values for DynamoDB."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _sanitize_for_dynamodb(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_sanitize_for_dynamodb(v) for v in obj]
    return obj


def _decode_payload(event: dict[str, Any]) -> dict[str, Any]:
    """Decompress and decode a CW Logs subscription filter payload."""
    compressed = base64.b64decode(event["awslogs"]["data"])
    decompressed = gzip.decompress(compressed)
    return json.loads(decompressed)


def _parse_log_event(log_event: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a single CW Logs log event into a normalized record.

    Returns None if the event should be skipped.
    """
    try:
        message = json.loads(log_event["message"])
    except (json.JSONDecodeError, KeyError):
        return None

    event_type = message.get("event")
    if event_type not in SUPPORTED_EVENTS:
        return None

    call_id = message.get("call_id")
    if not call_id:
        return None

    timestamp = message.get("timestamp", log_event.get("timestamp", ""))
    # CW Logs timestamp is epoch millis; structlog timestamp is ISO string
    if isinstance(timestamp, (int, float)):
        from datetime import datetime, timezone

        timestamp = datetime.fromtimestamp(
            timestamp / 1000, tz=timezone.utc
        ).isoformat()

    session_id = message.get("session_id", "")
    turn_number = message.get("turn_number")

    item: dict[str, Any] = {
        "PK": f"CALL#{call_id}",
        "SK": f"TS#{timestamp}#{event_type}",
        "call_id": call_id,
        "session_id": session_id,
        "event_type": event_type,
        "timestamp": timestamp,
        "TTL": int(time.time()) + EVENT_TTL_DAYS * 86400,
    }

    if turn_number is not None:
        item["turn_number"] = turn_number

    # Store the full event data minus the fields we already extracted
    data = {
        k: v
        for k, v in message.items()
        if k not in ("event", "call_id", "session_id", "timestamp", "turn_number")
    }
    if data:
        item["data"] = _sanitize_for_dynamodb(data)

    # GSI1: Calls by date + disposition (populated on session_ended / call_metrics_summary)
    if event_type == "session_ended":
        date_str = timestamp[:10] if isinstance(timestamp, str) else ""
        disposition = message.get("end_status", "unknown")
        item["GSI1PK"] = f"DATE#{date_str}"
        item["GSI1SK"] = f"DISP#{disposition}#{call_id}"
    elif event_type == "call_metrics_summary":
        date_str = timestamp[:10] if isinstance(timestamp, str) else ""
        item["GSI1PK"] = f"DATE#{date_str}"
        item["GSI1SK"] = f"SUMMARY#{call_id}"

    # GSI2: Calls by tool usage (populated on tool_execution / a2a events)
    if event_type == "tool_execution":
        tool_name = message.get("tool_name", "unknown")
        date_str = timestamp[:10] if isinstance(timestamp, str) else ""
        item["GSI2PK"] = f"TOOL#{tool_name}"
        item["GSI2SK"] = f"DATE#{date_str}#{call_id}"
    elif event_type.startswith("a2a_tool_call_") or event_type.startswith(
        "flow_a2a_call_"
    ):
        skill_id = message.get("skill_id", "unknown")
        date_str = timestamp[:10] if isinstance(timestamp, str) else ""
        item["GSI2PK"] = f"TOOL#{skill_id}"
        item["GSI2SK"] = f"DATE#{date_str}#{call_id}"

    return item


def _batch_write(items: list[dict[str, Any]]) -> int:
    """Write items to DynamoDB in batches of 25 with retry for unprocessed items."""
    written = 0
    for i in range(0, len(items), 25):
        batch = items[i : i + 25]
        request_items = {
            EVENTS_TABLE_NAME: [{"PutRequest": {"Item": item}} for item in batch]
        }

        retries = 0
        while request_items and retries < 3:
            try:
                response = dynamodb.meta.client.batch_write_item(
                    RequestItems=request_items
                )
                unprocessed = response.get("UnprocessedItems", {})
                written += len(batch) - sum(len(v) for v in unprocessed.values())
                request_items = unprocessed
                if request_items:
                    retries += 1
                    time.sleep(0.1 * (2**retries))
            except ClientError as e:
                logger.error(
                    "batch_write_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                    batch_size=len(batch),
                    retry=retries,
                )
                retries += 1
                if retries >= 3:
                    raise

    return written


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda handler for CW Logs subscription filter events."""
    try:
        payload = _decode_payload(event)
    except Exception as e:
        logger.error("payload_decode_failed", error=str(e), error_type=type(e).__name__)
        return {"statusCode": 400, "body": "Failed to decode payload"}

    log_events = payload.get("logEvents", [])
    logger.info(
        "ingestion_started",
        log_group=payload.get("logGroup"),
        log_stream=payload.get("logStream"),
        event_count=len(log_events),
    )

    items = []
    skipped = 0
    for log_event in log_events:
        item = _parse_log_event(log_event)
        if item:
            items.append(item)
        else:
            skipped += 1

    if not items:
        logger.info("ingestion_complete", written=0, skipped=skipped)
        return {"statusCode": 200, "body": "No events to write"}

    written = _batch_write(items)

    logger.info(
        "ingestion_complete",
        written=written,
        skipped=skipped,
        total=len(log_events),
    )

    return {"statusCode": 200, "body": f"Wrote {written} events"}
