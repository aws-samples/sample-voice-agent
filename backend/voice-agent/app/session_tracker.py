"""
Session Tracker - DynamoDB-based session tracking for voice agents.

Tracks active sessions across ECS tasks for:
- Real-time session counting for auto-scaling
- Per-task session visibility
- Health monitoring via heartbeats

Usage:
    tracker = SessionTracker(table_name="voice-agent-sessions-prod", task_id="abc123")

    # On call start
    await tracker.start_session(session_id, call_id)

    # On first audio
    await tracker.activate_session(session_id)

    # On call end
    await tracker.end_session(session_id, "completed", turn_count=5)

    # Heartbeat loop (run in background)
    await tracker.start_heartbeat_loop(lambda: len(active_sessions))
"""

import asyncio
import json
import os
import time
from typing import Callable, Optional

import structlog

logger = structlog.get_logger(__name__)

# Lazy import boto3 to allow testing without AWS dependencies
_dynamodb_resource = None


def _get_dynamodb():
    """Lazy-load DynamoDB resource."""
    global _dynamodb_resource
    if _dynamodb_resource is None:
        import boto3

        _dynamodb_resource = boto3.resource("dynamodb")
    return _dynamodb_resource


def get_ecs_task_id() -> str:
    """
    Get the ECS task ID from container metadata.

    Uses the ECS_CONTAINER_METADATA_URI_V4 environment variable to fetch
    task metadata. Falls back to a generated ID for local development.

    Returns:
        ECS task ID (e.g., "1234567890abcdef0")
    """
    metadata_uri = os.environ.get("ECS_CONTAINER_METADATA_URI_V4")

    if metadata_uri:
        try:
            import urllib.request

            # Fetch task metadata from ECS agent
            with urllib.request.urlopen(f"{metadata_uri}/task", timeout=2) as response:
                metadata = json.loads(response.read().decode())
                # TaskARN format: arn:aws:ecs:region:account:task/cluster/task-id
                task_arn = metadata.get("TaskARN", "")
                if task_arn:
                    return task_arn.split("/")[-1]
        except Exception as e:
            logger.warning("ecs_metadata_fetch_failed", error=str(e))

    # Fallback for local development or metadata unavailable
    return f"local-{os.getpid()}"


class SessionTracker:
    """
    Tracks voice agent sessions in DynamoDB.

    Provides methods for session lifecycle management and task health heartbeats.
    All operations use exponential backoff retry for resilience.
    """

    # TTL durations in seconds
    TTL_ACTIVE_SESSION = 24 * 60 * 60  # 24 hours for active sessions
    TTL_ENDED_SESSION = 60 * 60  # 1 hour for ended sessions
    TTL_HEARTBEAT = 5 * 60  # 5 minutes for heartbeats

    # Retry configuration
    MAX_RETRIES = 3
    INITIAL_BACKOFF_MS = 100

    # Heartbeat interval
    HEARTBEAT_INTERVAL_SECONDS = 30

    # Escalate heartbeat failures to ERROR after this many consecutive failures
    HEARTBEAT_ESCALATION_THRESHOLD = 5

    def __init__(self, table_name: str, task_id: str):
        """
        Initialize SessionTracker.

        Args:
            table_name: DynamoDB table name
            task_id: ECS task ID (use get_ecs_task_id())
        """
        self.table_name = table_name
        self.task_id = task_id
        self._table = None
        self._heartbeat_task: Optional[asyncio.Task] = None

        logger.info(
            "session_tracker_initialized",
            table_name=table_name,
            task_id=task_id,
        )

    @property
    def table(self):
        """Lazy-load DynamoDB table."""
        if self._table is None:
            self._table = _get_dynamodb().Table(self.table_name)
        return self._table

    async def start_session(self, session_id: str, call_id: str) -> bool:
        """
        Record session start in DynamoDB.

        Creates a session item with status "starting". This should be called
        when a new call request is received, before the pipeline starts.

        Args:
            session_id: Unique session identifier
            call_id: Correlation ID for the call

        Returns:
            True if write succeeded, False otherwise

        Raises:
            Exception: If DynamoDB write fails after retries (required mode)
        """
        current_time = int(time.time())
        ttl = current_time + self.TTL_ACTIVE_SESSION

        item = {
            "PK": f"SESSION#{session_id}",
            "SK": "METADATA",
            "session_id": session_id,
            "call_id": call_id,
            "task_id": self.task_id,
            "status": "starting",
            "started_at": current_time,
            "updated_at": current_time,
            "TTL": ttl,
            # GSI1: Query by status
            "GSI1PK": "STATUS#starting",
            "GSI1SK": f"{current_time}#{session_id}",
            # GSI2: Query by task
            "GSI2PK": f"TASK#{self.task_id}",
            "GSI2SK": f"{current_time}#{session_id}",
        }

        success = await self._put_item_with_retry(item)
        if success:
            logger.info(
                "session_started",
                session_id=session_id,
                call_id=call_id,
                task_id=self.task_id,
            )
        else:
            logger.error(
                "session_start_failed",
                session_id=session_id,
                call_id=call_id,
            )
            raise Exception(f"Failed to start session {session_id} in DynamoDB")

        return success

    async def activate_session(self, session_id: str) -> bool:
        """
        Update session status to "active".

        Called when the pipeline actually starts processing (e.g., first audio).

        Args:
            session_id: Session to activate

        Returns:
            True if update succeeded
        """
        current_time = int(time.time())

        update_expr = "SET #status = :status, updated_at = :updated_at, GSI1PK = :gsi1pk, GSI1SK = :gsi1sk"
        expr_values = {
            ":status": "active",
            ":updated_at": current_time,
            ":gsi1pk": "STATUS#active",
            ":gsi1sk": f"{current_time}#{session_id}",
        }
        expr_names = {"#status": "status"}

        success = await self._update_item_with_retry(
            key={"PK": f"SESSION#{session_id}", "SK": "METADATA"},
            update_expression=update_expr,
            expression_attribute_values=expr_values,
            expression_attribute_names=expr_names,
        )

        if success:
            logger.debug("session_activated", session_id=session_id)

        return success

    async def end_session(
        self,
        session_id: str,
        end_status: str,
        turn_count: int = 0,
        error_category: Optional[str] = None,
    ) -> bool:
        """
        Record session end in DynamoDB.

        Updates session status to "ended" with completion details.

        Args:
            session_id: Session to end
            end_status: "completed", "cancelled", or "error"
            turn_count: Number of conversation turns
            error_category: Error category if end_status is "error"

        Returns:
            True if update succeeded
        """
        current_time = int(time.time())
        ttl = current_time + self.TTL_ENDED_SESSION

        update_expr = (
            "SET #status = :status, "
            "end_status = :end_status, "
            "ended_at = :ended_at, "
            "updated_at = :updated_at, "
            "turn_count = :turn_count, "
            "#ttl = :ttl, "
            "GSI1PK = :gsi1pk, "
            "GSI1SK = :gsi1sk"
        )
        expr_values = {
            ":status": "ended",
            ":end_status": end_status,
            ":ended_at": current_time,
            ":updated_at": current_time,
            ":turn_count": turn_count,
            ":ttl": ttl,
            ":gsi1pk": "STATUS#ended",
            ":gsi1sk": f"{current_time}#{session_id}",
        }
        expr_names = {"#status": "status", "#ttl": "TTL"}

        # Add error category if present
        if error_category:
            update_expr += ", error_category = :error_category"
            expr_values[":error_category"] = error_category

        success = await self._update_item_with_retry(
            key={"PK": f"SESSION#{session_id}", "SK": "METADATA"},
            update_expression=update_expr,
            expression_attribute_values=expr_values,
            expression_attribute_names=expr_names,
        )

        if success:
            logger.info(
                "session_ended",
                session_id=session_id,
                end_status=end_status,
                turn_count=turn_count,
                error_category=error_category,
            )

        return success

    async def heartbeat(self, active_count: int) -> bool:
        """
        Send task heartbeat to DynamoDB.

        Updates the task heartbeat record with current timestamp and session count.
        Used by the session counter Lambda to identify healthy tasks.

        Args:
            active_count: Number of active sessions on this task

        Returns:
            True if heartbeat succeeded
        """
        current_time = int(time.time())
        ttl = current_time + self.TTL_HEARTBEAT

        item = {
            "PK": f"TASK#{self.task_id}",
            "SK": "HEARTBEAT",
            "task_id": self.task_id,
            "active_session_count": active_count,
            "updated_at": current_time,
            "TTL": ttl,
        }

        success = await self._put_item_with_retry(item)
        if success:
            logger.debug(
                "heartbeat_sent",
                task_id=self.task_id,
                active_count=active_count,
            )

        return success

    async def start_heartbeat_loop(
        self,
        get_count_fn: Callable[[], int],
    ) -> None:
        """
        Start background heartbeat loop.

        Sends heartbeats every HEARTBEAT_INTERVAL_SECONDS with current session count.

        Args:
            get_count_fn: Function that returns current active session count
        """
        if self._heartbeat_task is not None:
            logger.warning("heartbeat_loop_already_running")
            return

        async def _loop():
            consecutive_failures = 0
            while True:
                try:
                    count = get_count_fn()
                    await self.heartbeat(count)
                    if consecutive_failures > 0:
                        logger.info(
                            "heartbeat_recovered",
                            previous_failures=consecutive_failures,
                            task_id=self.task_id,
                        )
                    consecutive_failures = 0
                except Exception as e:
                    consecutive_failures += 1
                    if consecutive_failures >= self.HEARTBEAT_ESCALATION_THRESHOLD:
                        logger.error(
                            "heartbeat_persistent_failure",
                            error=str(e),
                            error_type=type(e).__name__,
                            consecutive_failures=consecutive_failures,
                            blind_duration_seconds=consecutive_failures
                            * self.HEARTBEAT_INTERVAL_SECONDS,
                            task_id=self.task_id,
                        )
                    else:
                        logger.warning(
                            "heartbeat_failed",
                            error=str(e),
                            error_type=type(e).__name__,
                            consecutive_failures=consecutive_failures,
                            task_id=self.task_id,
                        )
                await asyncio.sleep(self.HEARTBEAT_INTERVAL_SECONDS)

        self._heartbeat_task = asyncio.create_task(_loop())
        logger.info("heartbeat_loop_started", interval=self.HEARTBEAT_INTERVAL_SECONDS)

    async def stop_heartbeat_loop(self) -> None:
        """Stop the background heartbeat loop."""
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
            logger.info("heartbeat_loop_stopped")

    async def _put_item_with_retry(self, item: dict) -> bool:
        """
        Put item to DynamoDB with exponential backoff retry.

        Args:
            item: Item to write

        Returns:
            True if write succeeded
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                # Run blocking boto3 call in executor
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, lambda: self.table.put_item(Item=item))
                return True
            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    backoff_ms = self.INITIAL_BACKOFF_MS * (2**attempt)
                    logger.warning(
                        "dynamodb_put_retry",
                        attempt=attempt + 1,
                        backoff_ms=backoff_ms,
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                    await asyncio.sleep(backoff_ms / 1000)
                else:
                    logger.error(
                        "dynamodb_put_failed",
                        attempts=self.MAX_RETRIES,
                        error=str(e),
                        error_type=type(e).__name__,
                        table_name=self.table_name,
                        pk=item.get("PK"),
                        sk=item.get("SK"),
                    )
                    return False
        return False

    async def _update_item_with_retry(
        self,
        key: dict,
        update_expression: str,
        expression_attribute_values: dict,
        expression_attribute_names: Optional[dict] = None,
    ) -> bool:
        """
        Update item in DynamoDB with exponential backoff retry.

        Returns:
            True if update succeeded
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                loop = asyncio.get_event_loop()
                kwargs = {
                    "Key": key,
                    "UpdateExpression": update_expression,
                    "ExpressionAttributeValues": expression_attribute_values,
                }
                if expression_attribute_names:
                    kwargs["ExpressionAttributeNames"] = expression_attribute_names

                await loop.run_in_executor(
                    None, lambda: self.table.update_item(**kwargs)
                )
                return True
            except Exception as e:
                if attempt < self.MAX_RETRIES - 1:
                    backoff_ms = self.INITIAL_BACKOFF_MS * (2**attempt)
                    logger.warning(
                        "dynamodb_update_retry",
                        attempt=attempt + 1,
                        backoff_ms=backoff_ms,
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                    await asyncio.sleep(backoff_ms / 1000)
                else:
                    logger.error(
                        "dynamodb_update_failed",
                        attempts=self.MAX_RETRIES,
                        error=str(e),
                        error_type=type(e).__name__,
                        table_name=self.table_name,
                        pk=key.get("PK"),
                        sk=key.get("SK"),
                    )
                    return False
        return False
