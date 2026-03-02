"""Tests for hangup_tool.

Covers:
- ToolDefinition metadata (name, capabilities, category)
- Catalog registration
- Executor success path (queue_frame called with EndFrame)
- Executor error path (queue_frame is None)
- Executor error path (queue_frame raises exception)
- Reason logging
"""

import pytest
from unittest.mock import AsyncMock

try:
    from pipecat.frames.frames import EndFrame
except ImportError:
    pytest.skip(
        "pipecat not available (container-only dependency)", allow_module_level=True
    )

from app.tools.builtin.hangup_tool import hangup_tool, hangup_executor
from app.tools.capabilities import PipelineCapability
from app.tools.context import ToolContext
from app.tools.result import ToolStatus
from app.tools.schema import ToolCategory


# =============================================================================
# ToolDefinition Tests
# =============================================================================


class TestHangupToolDefinition:
    """Test tool definition and capabilities."""

    def test_tool_name(self):
        assert hangup_tool.name == "hangup_call"

    def test_category(self):
        assert hangup_tool.category == ToolCategory.SYSTEM

    def test_requires_transport(self):
        assert hangup_tool.requires == frozenset({PipelineCapability.TRANSPORT})

    def test_has_reason_parameter(self):
        param_names = [p.name for p in hangup_tool.parameters]
        assert "reason" in param_names

    def test_reason_parameter_is_required(self):
        reason_param = next(p for p in hangup_tool.parameters if p.name == "reason")
        assert reason_param.required is True

    def test_timeout(self):
        assert hangup_tool.timeout_seconds == 5.0

    def test_registered_in_catalog(self):
        from app.tools.builtin.catalog import ALL_LOCAL_TOOLS

        assert hangup_tool in ALL_LOCAL_TOOLS

    def test_description_mentions_end_call(self):
        assert "end" in hangup_tool.description.lower()

    def test_bedrock_tool_spec_format(self):
        spec = hangup_tool.to_bedrock_tool_spec()
        assert "toolSpec" in spec
        assert spec["toolSpec"]["name"] == "hangup_call"


# =============================================================================
# Executor Tests
# =============================================================================


class TestHangupExecutor:
    """Test tool execution logic."""

    @pytest.fixture
    def mock_queue_frame(self):
        """Mock queue_frame callback."""
        return AsyncMock()

    @pytest.fixture
    def context(self, mock_queue_frame):
        """Create a ToolContext with a mock queue_frame."""
        return ToolContext(
            call_id="test-call-123",
            session_id="test-session-456",
            turn_number=5,
            queue_frame=mock_queue_frame,
        )

    @pytest.fixture
    def context_no_queue_frame(self):
        """Create a ToolContext without queue_frame (simulates missing wiring)."""
        return ToolContext(
            call_id="test-call-123",
            session_id="test-session-456",
        )

    @pytest.mark.asyncio
    async def test_success_queues_endframe(self, context, mock_queue_frame):
        """Executor should queue an EndFrame when queue_frame is available."""
        result = await hangup_executor({"reason": "Issue resolved"}, context)

        assert result.status == ToolStatus.SUCCESS
        assert result.is_success()
        mock_queue_frame.assert_called_once()

        # Verify it was called with an EndFrame
        queued_frame = mock_queue_frame.call_args[0][0]
        assert isinstance(queued_frame, EndFrame)

    @pytest.mark.asyncio
    async def test_success_result_content(self, context):
        """Result should contain hangup confirmation data."""
        result = await hangup_executor({"reason": "Customer satisfied"}, context)

        assert result.status == ToolStatus.SUCCESS
        assert result.content["hangup_initiated"] is True
        assert result.content["reason"] == "Customer satisfied"
        assert result.content["call_id"] == "test-call-123"
        assert "message" in result.content

    @pytest.mark.asyncio
    async def test_success_result_suppresses_llm_reinference(self, context):
        """Hangup result should set run_llm=False to prevent redundant LLM call."""
        result = await hangup_executor({"reason": "Call complete"}, context)

        assert result.status == ToolStatus.SUCCESS
        assert result.run_llm is False

    @pytest.mark.asyncio
    async def test_error_result_does_not_suppress_llm(self, context_no_queue_frame):
        """Error results should not suppress LLM (default None lets Pipecat decide)."""
        result = await hangup_executor({"reason": "Done"}, context_no_queue_frame)

        assert result.status == ToolStatus.ERROR
        assert result.run_llm is None

    @pytest.mark.asyncio
    async def test_default_reason(self, context):
        """Executor should use a default reason when none provided."""
        result = await hangup_executor({}, context)

        assert result.status == ToolStatus.SUCCESS
        assert result.content["reason"] == "Conversation concluded"

    @pytest.mark.asyncio
    async def test_error_when_no_queue_frame(self, context_no_queue_frame):
        """Executor should return error when queue_frame is None."""
        result = await hangup_executor({"reason": "Done"}, context_no_queue_frame)

        assert result.status == ToolStatus.ERROR
        assert not result.is_success()
        assert result.error_code == "HANGUP_UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_error_when_queue_frame_raises(self, context, mock_queue_frame):
        """Executor should handle exceptions from queue_frame gracefully."""
        mock_queue_frame.side_effect = RuntimeError("Pipeline crashed")

        result = await hangup_executor({"reason": "Done"}, context)

        assert result.status == ToolStatus.ERROR
        assert result.error_code == "HANGUP_FAILED"

    @pytest.mark.asyncio
    async def test_queue_frame_not_called_when_none(self, context_no_queue_frame):
        """Verify no attempt to call None queue_frame."""
        result = await hangup_executor({"reason": "Done"}, context_no_queue_frame)

        # Should return error, not raise AttributeError
        assert result.status == ToolStatus.ERROR


# =============================================================================
# Capability Gating Tests
# =============================================================================


class TestHangupCapabilityGating:
    """Test that the tool is correctly gated by capabilities."""

    def test_registers_with_transport_capability(self):
        """Tool should be included when TRANSPORT capability is available."""
        available = frozenset({PipelineCapability.BASIC, PipelineCapability.TRANSPORT})
        assert hangup_tool.requires <= available

    def test_excluded_without_transport_capability(self):
        """Tool should be excluded when only BASIC capability is available."""
        available = frozenset({PipelineCapability.BASIC})
        assert not (hangup_tool.requires <= available)

    def test_does_not_require_sip_session(self):
        """Hangup should work for both SIP and WebRTC -- no SIP required."""
        assert PipelineCapability.SIP_SESSION not in hangup_tool.requires

    def test_does_not_require_transfer_destination(self):
        """Hangup doesn't need a transfer destination."""
        assert PipelineCapability.TRANSFER_DESTINATION not in hangup_tool.requires
