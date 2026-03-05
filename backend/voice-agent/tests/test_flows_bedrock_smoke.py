"""Smoke tests for Pipecat Flows + AWSBedrockLLMService compatibility.

Validates that FlowManager works with AWSBedrockLLMService at pipecat v0.0.102.
This is Phase 0 of the multi-agent-handoff feature -- a blocking prerequisite.

Tests verify:
    - FlowManager initializes with Bedrock LLM and universal LLMContext
    - Direct functions are accepted as node functions
    - global_functions are available in every node
    - Node transitions swap context (system prompt + tools)
    - RESET_WITH_SUMMARY produces a summary in the new context
    - ContextStrategy.APPEND carries full history

These tests mock the LLM service and transport to run without AWS credentials
or a Daily room. They exercise the FlowManager's internal machinery (adapter
selection, function registration, context frame generation) without performing
actual inference.

Run with: pytest tests/test_flows_bedrock_smoke.py -v
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from pipecat.adapters.schemas.function_schema import FunctionSchema
    from pipecat.adapters.schemas.tools_schema import ToolsSchema
    from pipecat.frames.frames import (
        LLMMessagesUpdateFrame,
        LLMRunFrame,
        LLMSetToolsFrame,
    )
    from pipecat.pipeline.task import PipelineTask
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
        LLMUserAggregatorParams,
    )
    from pipecat.services.llm_service import FunctionCallParams

    from pipecat_flows import (
        ContextStrategy,
        ContextStrategyConfig,
        FlowManager,
        FlowResult,
        NodeConfig,
    )
except ImportError:
    pytest.skip(
        "Container-only dependencies not available (pipecat/pipecat-flows)",
        allow_module_level=True,
    )


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_llm():
    """Create a mock AWSBedrockLLMService."""
    llm = MagicMock()
    llm.__class__.__name__ = "AWSBedrockLLMService"
    llm.__class__.__module__ = "pipecat.services.aws.llm"
    llm.register_function = MagicMock()
    # Mock run_inference for summary generation
    llm.run_inference = AsyncMock(return_value="Summary: caller has a WiFi issue.")
    return llm


@pytest.fixture
def context_and_aggregator():
    """Create a universal LLMContext and LLMContextAggregatorPair.

    Uses universal LLMContext (not OpenAILLMContext) which triggers the
    UniversalLLMAdapter in Flows -- the code path we need to validate.
    """
    context = LLMContext()
    # Mock the VAD analyzer to avoid Silero dependency
    mock_vad = MagicMock()
    aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=mock_vad),
    )
    return context, aggregator


@pytest.fixture
def mock_task(context_and_aggregator):
    """Create a mock PipelineTask that captures queued frames."""
    _, aggregator = context_and_aggregator
    task = MagicMock(spec=PipelineTask)
    task.queue_frames = AsyncMock()
    task.queue_frame = AsyncMock()
    return task


@pytest.fixture
def mock_transport():
    """Create a mock DailyTransport."""
    transport = MagicMock()
    transport.event_handler = MagicMock(return_value=lambda f: f)
    return transport


# =============================================================================
# Direct function definitions for test nodes
# =============================================================================


async def transfer_to_specialist(
    flow_manager: FlowManager, reason: str
) -> tuple[FlowResult, NodeConfig]:
    """Transfer the caller to a specialist agent.

    Args:
        reason: Brief explanation of why the transfer is needed.
    """
    return {"status": "transferred", "reason": reason}, create_specialist_node()


async def return_to_reception(
    flow_manager: FlowManager,
) -> tuple[FlowResult, NodeConfig]:
    """Return to the reception agent after the specialist task is complete."""
    return {"status": "returned"}, create_reception_node()


async def get_time(flow_manager: FlowManager) -> tuple[FlowResult, None]:
    """Get the current time. Always available as a global function."""
    return {"time": "2026-03-04T12:00:00"}, None


# =============================================================================
# Node creation functions
# =============================================================================


def create_reception_node() -> NodeConfig:
    """Create the reception/orchestrator node."""
    return NodeConfig(
        name="reception",
        role_messages=[
            {
                "role": "system",
                "content": "You are a friendly receptionist. Identify the caller's intent and route them.",
            }
        ],
        task_messages=[
            {
                "role": "system",
                "content": "Greet the caller and ask how you can help.",
            }
        ],
        functions=[transfer_to_specialist],
    )


def create_specialist_node() -> NodeConfig:
    """Create a specialist node with APPEND context strategy (simple transition)."""
    return NodeConfig(
        name="specialist",
        role_messages=[
            {
                "role": "system",
                "content": "You are a computer support specialist.",
            }
        ],
        task_messages=[
            {
                "role": "system",
                "content": "Help the caller troubleshoot their issue step by step.",
            }
        ],
        functions=[return_to_reception],
    )


def create_specialist_node_with_summary() -> NodeConfig:
    """Create a specialist node with RESET_WITH_SUMMARY context strategy."""
    return NodeConfig(
        name="specialist_summary",
        role_messages=[
            {
                "role": "system",
                "content": "You are a computer support specialist.",
            }
        ],
        task_messages=[
            {
                "role": "system",
                "content": "Help the caller troubleshoot their issue step by step.",
            }
        ],
        functions=[return_to_reception],
        context_strategy=ContextStrategyConfig(
            strategy=ContextStrategy.RESET_WITH_SUMMARY,
            summary_prompt="Summarize the caller's technical issue and any details provided.",
        ),
    )


# =============================================================================
# Test: FlowManager initialization with Bedrock
# =============================================================================


class TestFlowManagerInitialization:
    """Test that FlowManager initializes correctly with Bedrock LLM."""

    @pytest.mark.asyncio
    async def test_flow_manager_creates_with_bedrock_llm(
        self, mock_task, mock_llm, context_and_aggregator, mock_transport
    ):
        """FlowManager should accept AWSBedrockLLMService without error."""
        _, aggregator = context_and_aggregator

        flow_manager = FlowManager(
            task=mock_task,
            llm=mock_llm,
            context_aggregator=aggregator,
            transport=mock_transport,
        )

        assert flow_manager is not None
        assert flow_manager.current_node is None

    @pytest.mark.asyncio
    async def test_flow_manager_initializes_with_reception_node(
        self, mock_task, mock_llm, context_and_aggregator, mock_transport
    ):
        """FlowManager.initialize() should set the initial node and queue frames."""
        _, aggregator = context_and_aggregator

        flow_manager = FlowManager(
            task=mock_task,
            llm=mock_llm,
            context_aggregator=aggregator,
            transport=mock_transport,
        )

        await flow_manager.initialize(create_reception_node())

        assert flow_manager.current_node == "reception"
        # Should have queued frames: LLMMessagesUpdateFrame + LLMSetToolsFrame + LLMRunFrame
        assert mock_task.queue_frames.call_count >= 1

    @pytest.mark.asyncio
    async def test_flow_manager_registers_node_functions(
        self, mock_task, mock_llm, context_and_aggregator, mock_transport
    ):
        """Direct functions from the node should be registered with the LLM."""
        _, aggregator = context_and_aggregator

        flow_manager = FlowManager(
            task=mock_task,
            llm=mock_llm,
            context_aggregator=aggregator,
            transport=mock_transport,
        )

        await flow_manager.initialize(create_reception_node())

        # transfer_to_specialist should be registered
        registered_names = [
            call.args[0] for call in mock_llm.register_function.call_args_list
        ]
        assert "transfer_to_specialist" in registered_names


# =============================================================================
# Test: Global functions
# =============================================================================


class TestGlobalFunctions:
    """Test that global_functions are available in every node."""

    @pytest.mark.asyncio
    async def test_global_function_registered_in_initial_node(
        self, mock_task, mock_llm, context_and_aggregator, mock_transport
    ):
        """Global functions should be registered when the initial node is set."""
        _, aggregator = context_and_aggregator

        flow_manager = FlowManager(
            task=mock_task,
            llm=mock_llm,
            context_aggregator=aggregator,
            transport=mock_transport,
            global_functions=[get_time],
        )

        await flow_manager.initialize(create_reception_node())

        registered_names = [
            call.args[0] for call in mock_llm.register_function.call_args_list
        ]
        assert "get_time" in registered_names
        assert "transfer_to_specialist" in registered_names

    @pytest.mark.asyncio
    async def test_global_function_persists_across_node_transition(
        self, mock_task, mock_llm, context_and_aggregator, mock_transport
    ):
        """Global functions should still be registered after transitioning to a new node."""
        _, aggregator = context_and_aggregator

        flow_manager = FlowManager(
            task=mock_task,
            llm=mock_llm,
            context_aggregator=aggregator,
            transport=mock_transport,
            global_functions=[get_time],
        )

        await flow_manager.initialize(create_reception_node())

        # Manually transition to specialist node
        await flow_manager.set_node_from_config(create_specialist_node())

        assert flow_manager.current_node == "specialist"

        # get_time should still be registered (global functions persist)
        registered_names = [
            call.args[0] for call in mock_llm.register_function.call_args_list
        ]
        assert "get_time" in registered_names


# =============================================================================
# Test: Node transitions
# =============================================================================


class TestNodeTransitions:
    """Test that node transitions swap context correctly."""

    @pytest.mark.asyncio
    async def test_transition_changes_current_node(
        self, mock_task, mock_llm, context_and_aggregator, mock_transport
    ):
        """Transitioning to a new node should update current_node."""
        _, aggregator = context_and_aggregator

        flow_manager = FlowManager(
            task=mock_task,
            llm=mock_llm,
            context_aggregator=aggregator,
            transport=mock_transport,
        )

        await flow_manager.initialize(create_reception_node())
        assert flow_manager.current_node == "reception"

        await flow_manager.set_node_from_config(create_specialist_node())
        assert flow_manager.current_node == "specialist"

    @pytest.mark.asyncio
    async def test_transition_queues_context_update_frames(
        self, mock_task, mock_llm, context_and_aggregator, mock_transport
    ):
        """Node transition should queue context frame and LLMSetToolsFrame."""
        _, aggregator = context_and_aggregator

        flow_manager = FlowManager(
            task=mock_task,
            llm=mock_llm,
            context_aggregator=aggregator,
            transport=mock_transport,
        )

        await flow_manager.initialize(create_reception_node())
        mock_task.queue_frames.reset_mock()

        await flow_manager.set_node_from_config(create_specialist_node())

        # Inspect the frames that were queued
        all_queued_frames = []
        for call in mock_task.queue_frames.call_args_list:
            frames = call.args[0]
            all_queued_frames.extend(frames)

        frame_types = [type(f).__name__ for f in all_queued_frames]
        # Default strategy is APPEND, which uses LLMMessagesAppendFrame
        # (LLMMessagesUpdateFrame is used for the first node or RESET strategies)
        assert (
            "LLMMessagesAppendFrame" in frame_types
            or "LLMMessagesUpdateFrame" in frame_types
        )
        assert "LLMSetToolsFrame" in frame_types

    @pytest.mark.asyncio
    async def test_transition_registers_new_node_functions(
        self, mock_task, mock_llm, context_and_aggregator, mock_transport
    ):
        """After transition, the new node's functions should be registered."""
        _, aggregator = context_and_aggregator

        flow_manager = FlowManager(
            task=mock_task,
            llm=mock_llm,
            context_aggregator=aggregator,
            transport=mock_transport,
        )

        await flow_manager.initialize(create_reception_node())
        await flow_manager.set_node_from_config(create_specialist_node())

        registered_names = [
            call.args[0] for call in mock_llm.register_function.call_args_list
        ]
        assert "return_to_reception" in registered_names

    @pytest.mark.asyncio
    async def test_round_trip_reception_specialist_reception(
        self, mock_task, mock_llm, context_and_aggregator, mock_transport
    ):
        """Should support reception -> specialist -> reception round trip."""
        _, aggregator = context_and_aggregator

        flow_manager = FlowManager(
            task=mock_task,
            llm=mock_llm,
            context_aggregator=aggregator,
            transport=mock_transport,
        )

        await flow_manager.initialize(create_reception_node())
        assert flow_manager.current_node == "reception"

        await flow_manager.set_node_from_config(create_specialist_node())
        assert flow_manager.current_node == "specialist"

        await flow_manager.set_node_from_config(create_reception_node())
        assert flow_manager.current_node == "reception"

    @pytest.mark.asyncio
    async def test_initial_node_uses_update_frame(
        self, mock_task, mock_llm, context_and_aggregator, mock_transport
    ):
        """The first node should use LLMMessagesUpdateFrame (not Append)."""
        _, aggregator = context_and_aggregator

        flow_manager = FlowManager(
            task=mock_task,
            llm=mock_llm,
            context_aggregator=aggregator,
            transport=mock_transport,
        )

        await flow_manager.initialize(create_reception_node())

        all_queued_frames = []
        for call in mock_task.queue_frames.call_args_list:
            frames = call.args[0]
            all_queued_frames.extend(frames)

        frame_types = [type(f).__name__ for f in all_queued_frames]
        assert "LLMMessagesUpdateFrame" in frame_types


# =============================================================================
# Test: Context strategies
# =============================================================================


class TestContextStrategies:
    """Test RESET_WITH_SUMMARY and APPEND context strategies."""

    @pytest.mark.asyncio
    async def test_reset_with_summary_triggers_summary_generation(
        self, mock_task, mock_llm, context_and_aggregator, mock_transport
    ):
        """RESET_WITH_SUMMARY should call LLM for summary generation on transition."""
        context, aggregator = context_and_aggregator

        flow_manager = FlowManager(
            task=mock_task,
            llm=mock_llm,
            context_aggregator=aggregator,
            transport=mock_transport,
        )

        await flow_manager.initialize(create_reception_node())
        mock_task.queue_frames.reset_mock()

        # Transition to specialist with summary (which has RESET_WITH_SUMMARY)
        await flow_manager.set_node_from_config(create_specialist_node_with_summary())

        # run_inference should have been called for summary generation
        assert mock_llm.run_inference.call_count >= 1

    @pytest.mark.asyncio
    async def test_reset_with_summary_uses_update_frame(
        self, mock_task, mock_llm, context_and_aggregator, mock_transport
    ):
        """RESET_WITH_SUMMARY should use LLMMessagesUpdateFrame (not Append)."""
        _, aggregator = context_and_aggregator

        flow_manager = FlowManager(
            task=mock_task,
            llm=mock_llm,
            context_aggregator=aggregator,
            transport=mock_transport,
        )

        await flow_manager.initialize(create_reception_node())
        mock_task.queue_frames.reset_mock()

        await flow_manager.set_node_from_config(create_specialist_node_with_summary())

        all_queued_frames = []
        for call in mock_task.queue_frames.call_args_list:
            frames = call.args[0]
            all_queued_frames.extend(frames)

        frame_types = [type(f).__name__ for f in all_queued_frames]
        assert "LLMMessagesUpdateFrame" in frame_types

    @pytest.mark.asyncio
    async def test_append_strategy_does_not_generate_summary(
        self, mock_task, mock_llm, context_and_aggregator, mock_transport
    ):
        """APPEND strategy should not trigger summary generation."""
        _, aggregator = context_and_aggregator

        append_node = NodeConfig(
            name="append_test",
            task_messages=[{"role": "system", "content": "Test node."}],
            context_strategy=ContextStrategyConfig(
                strategy=ContextStrategy.APPEND,
            ),
        )

        flow_manager = FlowManager(
            task=mock_task,
            llm=mock_llm,
            context_aggregator=aggregator,
            transport=mock_transport,
        )

        await flow_manager.initialize(create_reception_node())
        mock_llm.run_inference.reset_mock()

        await flow_manager.set_node_from_config(append_node)

        # run_inference should NOT have been called (no summary needed)
        assert mock_llm.run_inference.call_count == 0


# =============================================================================
# Test: FlowManager state management
# =============================================================================


class TestFlowManagerState:
    """Test that FlowManager state persists across transitions."""

    @pytest.mark.asyncio
    async def test_state_persists_across_transitions(
        self, mock_task, mock_llm, context_and_aggregator, mock_transport
    ):
        """State set in one node should be accessible after transition."""
        _, aggregator = context_and_aggregator

        flow_manager = FlowManager(
            task=mock_task,
            llm=mock_llm,
            context_aggregator=aggregator,
            transport=mock_transport,
        )

        await flow_manager.initialize(create_reception_node())

        # Set state as if a tool had run
        flow_manager.state["caller_intent"] = "wifi_troubleshooting"
        flow_manager.state["caller_phone"] = "555-0100"

        await flow_manager.set_node_from_config(create_specialist_node())

        assert flow_manager.state["caller_intent"] == "wifi_troubleshooting"
        assert flow_manager.state["caller_phone"] == "555-0100"


# =============================================================================
# Test: Direct function metadata extraction
# =============================================================================


class TestDirectFunctionMetadata:
    """Test that direct functions have their schema correctly extracted."""

    def test_transfer_function_has_reason_parameter(self):
        """The transfer_to_specialist function should expose a 'reason' parameter."""
        from pipecat_flows.types import FlowsDirectFunctionWrapper

        wrapper = FlowsDirectFunctionWrapper(function=transfer_to_specialist)
        assert wrapper.name == "transfer_to_specialist"
        assert "reason" in wrapper.properties
        assert wrapper.properties["reason"]["type"] == "string"
        assert "reason" in wrapper.required

    def test_return_function_has_no_parameters(self):
        """The return_to_reception function should have no user-facing parameters."""
        from pipecat_flows.types import FlowsDirectFunctionWrapper

        wrapper = FlowsDirectFunctionWrapper(function=return_to_reception)
        assert wrapper.name == "return_to_reception"
        # flow_manager is the special first param and should be excluded
        assert len(wrapper.properties) == 0

    def test_global_function_extracts_correctly(self):
        """The get_time global function should extract metadata correctly."""
        from pipecat_flows.types import FlowsDirectFunctionWrapper

        wrapper = FlowsDirectFunctionWrapper(function=get_time)
        assert wrapper.name == "get_time"
        assert len(wrapper.properties) == 0
