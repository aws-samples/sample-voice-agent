"""
Tests for the SessionTracker DynamoDB session tracking module.

Run with: pytest tests/test_session_tracker.py -v
"""

import asyncio
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# Set environment variables before importing
os.environ["AWS_REGION"] = "us-east-1"

# SessionTracker requires structlog (container-only dependency)
try:
    from app.session_tracker import SessionTracker, get_ecs_task_id
except ImportError:
    pytest.skip(
        "Container-only dependencies not available (structlog)", allow_module_level=True
    )


class TestGetEcsTaskId:
    """Tests for get_ecs_task_id function."""

    def test_returns_local_id_without_metadata_uri(self):
        """Test fallback to local ID when ECS metadata not available."""
        from app.session_tracker import get_ecs_task_id

        with patch.dict(os.environ, {}, clear=True):
            task_id = get_ecs_task_id()
            assert task_id.startswith("local-")
            assert str(os.getpid()) in task_id

    def test_extracts_task_id_from_ecs_metadata(self):
        """Test extracting task ID from ECS metadata endpoint."""
        from app.session_tracker import get_ecs_task_id

        mock_metadata = {
            "TaskARN": "arn:aws:ecs:us-east-1:123456789012:task/my-cluster/abc123def456"
        }

        with patch.dict(
            os.environ, {"ECS_CONTAINER_METADATA_URI_V4": "http://169.254.170.2/v4"}
        ):
            with patch("urllib.request.urlopen") as mock_urlopen:
                mock_response = MagicMock()
                mock_response.read.return_value = (
                    str(mock_metadata).replace("'", '"').encode()
                )
                mock_response.__enter__ = lambda s: mock_response
                mock_response.__exit__ = lambda *args: None
                mock_urlopen.return_value = mock_response

                # Import json for proper parsing
                import json

                mock_response.read.return_value = json.dumps(mock_metadata).encode()

                task_id = get_ecs_task_id()
                assert task_id == "abc123def456"

    def test_falls_back_on_metadata_fetch_error(self):
        """Test fallback when metadata fetch fails."""
        from app.session_tracker import get_ecs_task_id

        with patch.dict(
            os.environ, {"ECS_CONTAINER_METADATA_URI_V4": "http://169.254.170.2/v4"}
        ):
            with patch(
                "urllib.request.urlopen", side_effect=Exception("Connection refused")
            ):
                task_id = get_ecs_task_id()
                assert task_id.startswith("local-")


class TestSessionTracker:
    """Tests for SessionTracker class."""

    @pytest.fixture
    def mock_table(self):
        """Create a mock DynamoDB table."""
        table = MagicMock()
        table.put_item = MagicMock()
        table.update_item = MagicMock()
        return table

    @pytest.fixture
    def tracker(self, mock_table):
        """Create a SessionTracker with mocked DynamoDB."""
        from app.session_tracker import SessionTracker

        tracker = SessionTracker(
            table_name="test-sessions",
            task_id="test-task-123",
        )
        tracker._table = mock_table
        return tracker

    @pytest.mark.asyncio
    async def test_start_session_creates_item(self, tracker, mock_table):
        """Test that start_session creates a DynamoDB item."""
        result = await tracker.start_session("session-1", "call-1")

        assert result is True
        mock_table.put_item.assert_called_once()

        # Verify the item structure
        call_args = mock_table.put_item.call_args
        item = call_args.kwargs["Item"]

        assert item["PK"] == "SESSION#session-1"
        assert item["SK"] == "METADATA"
        assert item["session_id"] == "session-1"
        assert item["call_id"] == "call-1"
        assert item["task_id"] == "test-task-123"
        assert item["status"] == "starting"
        assert item["GSI1PK"] == "STATUS#starting"
        assert item["GSI2PK"] == "TASK#test-task-123"
        assert "TTL" in item
        assert "started_at" in item
        assert "updated_at" in item

    @pytest.mark.asyncio
    async def test_start_session_raises_on_failure(self, tracker, mock_table):
        """Test that start_session raises exception on DynamoDB failure."""
        mock_table.put_item.side_effect = Exception("DynamoDB error")

        with pytest.raises(Exception) as exc_info:
            await tracker.start_session("session-1", "call-1")

        assert "Failed to start session" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_activate_session_updates_status(self, tracker, mock_table):
        """Test that activate_session updates status to active."""
        result = await tracker.activate_session("session-1")

        assert result is True
        mock_table.update_item.assert_called_once()

        # Verify update expression
        call_args = mock_table.update_item.call_args
        assert call_args.kwargs["Key"] == {"PK": "SESSION#session-1", "SK": "METADATA"}
        assert ":status" in call_args.kwargs["ExpressionAttributeValues"]
        assert call_args.kwargs["ExpressionAttributeValues"][":status"] == "active"
        assert (
            call_args.kwargs["ExpressionAttributeValues"][":gsi1pk"] == "STATUS#active"
        )

    @pytest.mark.asyncio
    async def test_end_session_updates_with_completion_details(
        self, tracker, mock_table
    ):
        """Test that end_session updates with completion details."""
        result = await tracker.end_session(
            session_id="session-1",
            end_status="completed",
            turn_count=5,
        )

        assert result is True
        mock_table.update_item.assert_called_once()

        call_args = mock_table.update_item.call_args
        expr_values = call_args.kwargs["ExpressionAttributeValues"]

        assert expr_values[":status"] == "ended"
        assert expr_values[":end_status"] == "completed"
        assert expr_values[":turn_count"] == 5
        assert expr_values[":gsi1pk"] == "STATUS#ended"
        assert "ended_at" in call_args.kwargs["UpdateExpression"]

    @pytest.mark.asyncio
    async def test_end_session_includes_error_category(self, tracker, mock_table):
        """Test that end_session includes error category when provided."""
        result = await tracker.end_session(
            session_id="session-1",
            end_status="error",
            turn_count=2,
            error_category="llm_error",
        )

        assert result is True

        call_args = mock_table.update_item.call_args
        expr_values = call_args.kwargs["ExpressionAttributeValues"]

        assert expr_values[":error_category"] == "llm_error"
        assert "error_category" in call_args.kwargs["UpdateExpression"]

    @pytest.mark.asyncio
    async def test_heartbeat_creates_task_record(self, tracker, mock_table):
        """Test that heartbeat creates/updates task heartbeat record."""
        result = await tracker.heartbeat(active_count=3)

        assert result is True
        mock_table.put_item.assert_called_once()

        call_args = mock_table.put_item.call_args
        item = call_args.kwargs["Item"]

        assert item["PK"] == "TASK#test-task-123"
        assert item["SK"] == "HEARTBEAT"
        assert item["task_id"] == "test-task-123"
        assert item["active_session_count"] == 3
        assert "TTL" in item
        assert "updated_at" in item


class TestSessionTrackerRetry:
    """Tests for SessionTracker retry behavior."""

    @pytest.fixture
    def mock_table(self):
        """Create a mock DynamoDB table."""
        return MagicMock()

    @pytest.fixture
    def tracker(self, mock_table):
        """Create a SessionTracker with mocked DynamoDB."""
        from app.session_tracker import SessionTracker

        tracker = SessionTracker(
            table_name="test-sessions",
            task_id="test-task-123",
        )
        tracker._table = mock_table
        # Speed up retries for testing
        tracker.INITIAL_BACKOFF_MS = 1
        return tracker

    @pytest.mark.asyncio
    async def test_put_item_retries_on_transient_failure(self, tracker, mock_table):
        """Test that put_item retries on transient failures."""
        # Fail twice, then succeed
        mock_table.put_item.side_effect = [
            Exception("Transient error 1"),
            Exception("Transient error 2"),
            None,  # Success
        ]

        result = await tracker.heartbeat(active_count=1)

        assert result is True
        assert mock_table.put_item.call_count == 3

    @pytest.mark.asyncio
    async def test_put_item_fails_after_max_retries(self, tracker, mock_table):
        """Test that put_item fails after max retries."""
        mock_table.put_item.side_effect = Exception("Persistent error")

        result = await tracker.heartbeat(active_count=1)

        assert result is False
        assert mock_table.put_item.call_count == 3  # MAX_RETRIES

    @pytest.mark.asyncio
    async def test_update_item_retries_on_transient_failure(self, tracker, mock_table):
        """Test that update_item retries on transient failures."""
        mock_table.update_item.side_effect = [
            Exception("Transient error"),
            None,  # Success
        ]

        result = await tracker.activate_session("session-1")

        assert result is True
        assert mock_table.update_item.call_count == 2


class TestSessionTrackerHeartbeatLoop:
    """Tests for SessionTracker heartbeat loop."""

    @pytest.fixture
    def mock_table(self):
        """Create a mock DynamoDB table."""
        return MagicMock()

    @pytest.fixture
    def tracker(self, mock_table):
        """Create a SessionTracker with mocked DynamoDB."""
        from app.session_tracker import SessionTracker

        tracker = SessionTracker(
            table_name="test-sessions",
            task_id="test-task-123",
        )
        tracker._table = mock_table
        # Speed up heartbeat for testing
        tracker.HEARTBEAT_INTERVAL_SECONDS = 0.01
        return tracker

    @pytest.mark.asyncio
    async def test_heartbeat_loop_sends_periodic_heartbeats(self, tracker, mock_table):
        """Test that heartbeat loop sends heartbeats periodically."""
        session_count = 2

        await tracker.start_heartbeat_loop(get_count_fn=lambda: session_count)

        # Wait for a few heartbeats
        await asyncio.sleep(0.05)

        # Stop the loop
        await tracker.stop_heartbeat_loop()

        # Should have sent at least 2 heartbeats
        assert mock_table.put_item.call_count >= 2

        # Verify heartbeat content
        call_args = mock_table.put_item.call_args
        item = call_args.kwargs["Item"]
        assert item["active_session_count"] == session_count

    @pytest.mark.asyncio
    async def test_heartbeat_loop_handles_errors_gracefully(self, tracker, mock_table):
        """Test that heartbeat loop continues on errors."""
        # Speed up retry backoff for this test
        tracker.INITIAL_BACKOFF_MS = 1

        # Fail first call, succeed after
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("First heartbeat failed")
            return None

        mock_table.put_item.side_effect = side_effect

        await tracker.start_heartbeat_loop(get_count_fn=lambda: 1)

        # Wait for multiple heartbeat attempts (longer wait due to retry delays)
        await asyncio.sleep(0.5)

        await tracker.stop_heartbeat_loop()

        # Should have continued sending heartbeats despite first failure
        # At minimum: initial fail + 2 retries + at least 1 more heartbeat cycle
        assert mock_table.put_item.call_count >= 2

    @pytest.mark.asyncio
    async def test_heartbeat_loop_can_be_stopped(self, tracker, mock_table):
        """Test that heartbeat loop can be stopped cleanly."""
        await tracker.start_heartbeat_loop(get_count_fn=lambda: 0)

        # Verify it's running
        assert tracker._heartbeat_task is not None

        # Stop it
        await tracker.stop_heartbeat_loop()

        # Verify it's stopped
        assert tracker._heartbeat_task is None

    @pytest.mark.asyncio
    async def test_multiple_start_calls_warn(self, tracker, mock_table):
        """Test that calling start twice logs a warning."""
        await tracker.start_heartbeat_loop(get_count_fn=lambda: 0)

        # Start again - should warn but not crash
        await tracker.start_heartbeat_loop(get_count_fn=lambda: 0)

        await tracker.stop_heartbeat_loop()


class TestSessionTrackerTTL:
    """Tests for SessionTracker TTL values."""

    def test_ttl_constants_are_reasonable(self):
        """Test that TTL constants have reasonable values."""
        from app.session_tracker import SessionTracker

        # Active sessions should live for 24 hours
        assert SessionTracker.TTL_ACTIVE_SESSION == 24 * 60 * 60

        # Ended sessions should live for 1 hour
        assert SessionTracker.TTL_ENDED_SESSION == 60 * 60

        # Heartbeats should live for 5 minutes
        assert SessionTracker.TTL_HEARTBEAT == 5 * 60

    @pytest.mark.asyncio
    async def test_session_ttl_is_set_correctly(self):
        """Test that session TTL is calculated correctly."""
        from app.session_tracker import SessionTracker

        mock_table = MagicMock()
        tracker = SessionTracker(
            table_name="test-sessions",
            task_id="test-task-123",
        )
        tracker._table = mock_table

        current_time = int(time.time())

        await tracker.start_session("session-1", "call-1")

        call_args = mock_table.put_item.call_args
        item = call_args.kwargs["Item"]

        # TTL should be ~24 hours from now (allow 5 second tolerance)
        expected_ttl = current_time + SessionTracker.TTL_ACTIVE_SESSION
        assert abs(item["TTL"] - expected_ttl) < 5

    @pytest.mark.asyncio
    async def test_ended_session_ttl_is_shorter(self):
        """Test that ended session has shorter TTL."""
        from app.session_tracker import SessionTracker

        mock_table = MagicMock()
        tracker = SessionTracker(
            table_name="test-sessions",
            task_id="test-task-123",
        )
        tracker._table = mock_table

        current_time = int(time.time())

        await tracker.end_session("session-1", "completed", turn_count=3)

        call_args = mock_table.update_item.call_args
        expr_values = call_args.kwargs["ExpressionAttributeValues"]

        # TTL should be ~1 hour from now
        expected_ttl = current_time + SessionTracker.TTL_ENDED_SESSION
        assert abs(expr_values[":ttl"] - expected_ttl) < 5
