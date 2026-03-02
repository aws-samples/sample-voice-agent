"""
Session Counter Lambda - Queries DynamoDB for active session counts.

Emits CloudWatch metrics for scaling decisions:
- VoiceAgent/Sessions/ActiveCount: Total active sessions across all tasks
- VoiceAgent/Sessions/HealthyTaskCount: Tasks with recent heartbeats
- VoiceAgent/Sessions/SessionsPerTask: Average sessions per healthy task

Also cleans up orphaned sessions from dead tasks to prevent phantom counts.

Triggered by CloudWatch Events every minute.
"""

import json
import os
import time
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types from DynamoDB."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            # Convert to int if whole number, else float
            if obj % 1 == 0:
                return int(obj)
            return float(obj)
        return super().default(obj)


# Initialize clients
dynamodb = boto3.resource("dynamodb")
cloudwatch = boto3.client("cloudwatch")

TABLE_NAME = os.environ.get("SESSION_TABLE_NAME", "")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "production")
NAMESPACE = "VoiceAgent/Sessions"

# Heartbeat staleness threshold (seconds)
# Tasks without heartbeat in this window are considered unhealthy
HEARTBEAT_STALENESS_SECONDS = 90


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for session counting.

    Queries DynamoDB to count:
    1. Active sessions (GSI1PK = STATUS#active)
    2. Healthy tasks (TASK heartbeats within staleness window)

    Cleans up orphaned sessions from dead tasks, then emits CloudWatch metrics.
    """
    if not TABLE_NAME:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "SESSION_TABLE_NAME not configured"}),
        }

    table = dynamodb.Table(TABLE_NAME)
    current_time = int(time.time())
    staleness_threshold = current_time - HEARTBEAT_STALENESS_SECONDS

    try:
        # Query active sessions -- returns full items so we can inspect task_id
        active_sessions = query_active_sessions(table)

        # Query healthy tasks (tasks with recent heartbeats)
        healthy_tasks, task_session_counts = query_healthy_tasks(
            table, staleness_threshold
        )

        healthy_task_set = set(healthy_tasks)

        # Clean up orphaned sessions from dead tasks.
        # If a container dies, end_session() never fires. The session stays
        # STATUS#active until its 24-hour TTL expires, inflating counts.
        # We detect these by checking if the session's task still has a heartbeat.
        orphaned = [
            s
            for s in active_sessions
            if s.get("task_id") and s["task_id"] not in healthy_task_set
        ]

        reaped_count = 0
        if orphaned:
            reaped_count = reap_orphaned_sessions(table, orphaned, current_time)
            print(
                json.dumps(
                    {
                        "event": "orphaned_sessions_reaped",
                        "count": reaped_count,
                        "session_ids": [s["session_id"] for s in orphaned],
                    }
                )
            )

        # Recount: subtract reaped orphans from the active count
        active_count = len(active_sessions) - reaped_count

        # Build per-task session counts from actual active session data.
        # This is more accurate than the heartbeat's active_session_count
        # because it reflects the real GSI state, not a periodic snapshot.
        live_task_counts: dict[str, int] = defaultdict(int)
        for session in active_sessions:
            task_id = session.get("task_id")
            if task_id and task_id in healthy_task_set:
                live_task_counts[task_id] += 1

        # Calculate sessions per task metrics
        # Avg: fleet-wide utilization (used for scale-in decisions)
        # Max: hottest single task (used for scale-out decisions)
        healthy_count = len(healthy_tasks)
        avg_sessions_per_task = active_count / healthy_count if healthy_count else 0
        max_sessions_per_task = (
            max(live_task_counts.values()) if live_task_counts else 0
        )

        # Emit CloudWatch metrics
        emit_metrics(
            active_count=active_count,
            healthy_task_count=healthy_count,
            avg_sessions_per_task=avg_sessions_per_task,
            max_sessions_per_task=max_sessions_per_task,
            task_session_counts=dict(live_task_counts),
            healthy_task_ids=healthy_tasks,
        )

        result = {
            "timestamp": datetime.utcnow().isoformat(),
            "activeSessionCount": active_count,
            "healthyTaskCount": healthy_count,
            "avgSessionsPerTask": round(avg_sessions_per_task, 2),
            "maxSessionsPerTask": max_sessions_per_task,
            "taskSessionCounts": dict(live_task_counts),
            "reapedOrphanedSessions": reaped_count,
        }

        print(
            json.dumps(
                {"event": "session_count_completed", **result}, cls=DecimalEncoder
            )
        )

        return {
            "statusCode": 200,
            "body": json.dumps(result, cls=DecimalEncoder),
        }

    except ClientError as e:
        error_msg = str(e)
        print(json.dumps({"event": "session_count_error", "error": error_msg}))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": error_msg}),
        }


def query_active_sessions(table: Any) -> list[dict]:
    """
    Query GSI1 for active sessions.

    Returns full session items (not just count) so we can inspect task_id
    for orphan detection and per-task counting.
    """
    items = []
    response = table.query(
        IndexName="GSI1",
        KeyConditionExpression="GSI1PK = :pk",
        ExpressionAttributeValues={":pk": "STATUS#active"},
        ProjectionExpression="PK, SK, session_id, task_id",
    )
    items.extend(response.get("Items", []))

    while "LastEvaluatedKey" in response:
        response = table.query(
            IndexName="GSI1",
            KeyConditionExpression="GSI1PK = :pk",
            ExpressionAttributeValues={":pk": "STATUS#active"},
            ProjectionExpression="PK, SK, session_id, task_id",
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    return items


def reap_orphaned_sessions(table: Any, orphaned: list[dict], current_time: int) -> int:
    """
    Mark orphaned sessions as ended.

    These are sessions stuck in STATUS#active whose tasks no longer have
    a heartbeat (container died without calling end_session).

    Args:
        table: DynamoDB table
        orphaned: List of session items to reap
        current_time: Current epoch seconds

    Returns:
        Number of sessions successfully reaped
    """
    reaped = 0
    ttl = current_time + 3600  # 1 hour TTL for ended sessions

    for session in orphaned:
        pk = session.get("PK", f"SESSION#{session.get('session_id', 'unknown')}")
        session_id = session.get("session_id", "unknown")

        try:
            table.update_item(
                Key={"PK": pk, "SK": "METADATA"},
                UpdateExpression=(
                    "SET #s = :status, end_status = :end_status, "
                    "ended_at = :ended_at, updated_at = :updated_at, "
                    "#ttl = :ttl, GSI1PK = :gsi1pk, GSI1SK = :gsi1sk"
                ),
                ExpressionAttributeNames={"#s": "status", "#ttl": "TTL"},
                ExpressionAttributeValues={
                    ":status": "ended",
                    ":end_status": "orphaned",
                    ":ended_at": current_time,
                    ":updated_at": current_time,
                    ":ttl": ttl,
                    ":gsi1pk": "STATUS#ended",
                    ":gsi1sk": f"{current_time}#{session_id}",
                },
            )
            reaped += 1
        except ClientError as e:
            print(
                json.dumps(
                    {
                        "event": "orphan_reap_failed",
                        "session_id": session_id,
                        "error": str(e),
                    }
                )
            )

    return reaped


def query_healthy_tasks(
    table: Any, staleness_threshold: int
) -> tuple[list[str], dict[str, int]]:
    """
    Query for tasks with recent heartbeats.

    Returns:
        - List of healthy task IDs
        - Dict mapping task_id -> active session count (from heartbeat)
    """
    healthy_tasks = []
    task_session_counts = {}

    # Scan for task heartbeats (small number expected)
    # Using a scan here because:
    # 1. Task count is small (typically < 100)
    # 2. Heartbeats have short TTL, so table is small
    # 3. We need to filter by TTL timestamp anyway
    response = table.scan(
        FilterExpression="begins_with(PK, :prefix) AND SK = :sk AND updated_at > :threshold",
        ExpressionAttributeValues={
            ":prefix": "TASK#",
            ":sk": "HEARTBEAT",
            ":threshold": staleness_threshold,
        },
        ProjectionExpression="PK, active_session_count",
    )

    for item in response.get("Items", []):
        task_id = item["PK"].replace("TASK#", "")
        healthy_tasks.append(task_id)
        task_session_counts[task_id] = item.get("active_session_count", 0)

    # Handle pagination if needed
    while "LastEvaluatedKey" in response:
        response = table.scan(
            FilterExpression="begins_with(PK, :prefix) AND SK = :sk AND updated_at > :threshold",
            ExpressionAttributeValues={
                ":prefix": "TASK#",
                ":sk": "HEARTBEAT",
                ":threshold": staleness_threshold,
            },
            ProjectionExpression="PK, active_session_count",
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        for item in response.get("Items", []):
            task_id = item["PK"].replace("TASK#", "")
            healthy_tasks.append(task_id)
            task_session_counts[task_id] = item.get("active_session_count", 0)

    return healthy_tasks, task_session_counts


def emit_metrics(
    active_count: int,
    healthy_task_count: int,
    avg_sessions_per_task: float,
    max_sessions_per_task: int,
    task_session_counts: dict[str, int] | None = None,
    healthy_task_ids: list[str] | None = None,
) -> None:
    """
    Emit CloudWatch custom metrics for monitoring and auto-scaling.

    Emits two sessions-per-task metrics:
    - SessionsPerTask (avg): fleet-wide utilization, used for scale-in
    - MaxSessionsPerTask: hottest single task, used for scale-out

    Also emits per-task breakdown:
    - SessionsPerTask with [Environment, TaskId] dimension for each healthy task
    - Idle healthy tasks emit 0 so they are visible in the SEARCH expression
    """
    timestamp = datetime.utcnow()
    dimensions = [{"Name": "Environment", "Value": ENVIRONMENT}]

    metric_data = [
        {
            "MetricName": "ActiveCount",
            "Timestamp": timestamp,
            "Value": active_count,
            "Unit": "Count",
            "Dimensions": dimensions,
        },
        {
            "MetricName": "HealthyTaskCount",
            "Timestamp": timestamp,
            "Value": healthy_task_count,
            "Unit": "Count",
            "Dimensions": dimensions,
        },
        {
            "MetricName": "SessionsPerTask",
            "Timestamp": timestamp,
            "Value": avg_sessions_per_task,
            "Unit": "Count",
            "Dimensions": dimensions,
        },
        {
            "MetricName": "MaxSessionsPerTask",
            "Timestamp": timestamp,
            "Value": max_sessions_per_task,
            "Unit": "Count",
            "Dimensions": dimensions,
        },
    ]

    # Per-task breakdown: emit SessionsPerTask with TaskId dimension
    # so each task gets its own CloudWatch time series.
    # Emit for ALL healthy tasks (including idle ones with 0 sessions)
    # so the SEARCH expression on the dashboard shows every running task.
    all_task_counts = dict(task_session_counts) if task_session_counts else {}
    if healthy_task_ids:
        for task_id in healthy_task_ids:
            if task_id not in all_task_counts:
                all_task_counts[task_id] = 0

    for task_id, session_count in all_task_counts.items():
        # Use short task ID (last 12 chars) for readable graph legends
        short_id = task_id[-12:] if len(task_id) > 12 else task_id
        metric_data.append(
            {
                "MetricName": "SessionsPerTask",
                "Timestamp": timestamp,
                "Value": session_count,
                "Unit": "Count",
                "Dimensions": [
                    {"Name": "Environment", "Value": ENVIRONMENT},
                    {"Name": "TaskId", "Value": short_id},
                ],
            }
        )

    # CloudWatch PutMetricData supports max 1000 metrics per call
    # With typical task counts (<100), we stay well under the limit
    cloudwatch.put_metric_data(
        Namespace=NAMESPACE,
        MetricData=metric_data,
    )
