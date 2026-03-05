"""Unit tests for the flow transition system.

Tests the generic transfer function, node factory registration,
loop protection, self-transfer handling, unknown target handling,
and observability wiring (metrics collector integration).

Note: NodeConfig is a TypedDict, so fields are accessed via dict syntax.

Run with: .venv/bin/python -m pytest tests/test_flow_transitions.py -v
"""

import pytest
from unittest.mock import MagicMock, patch, call

try:
    from pipecat_flows import NodeConfig

    from app.flows.transitions import (
        transfer,
        register_node_factory,
        get_available_targets,
        clear_node_factories,
        DEFAULT_MAX_TRANSITIONS,
        _TRANSITION_COUNT_KEY,
        _TRANSITION_HISTORY_KEY,
        _COLLECTOR_KEY,
    )
except ImportError:
    pytest.skip(
        "Container-only dependencies not available (pipecat-flows)",
        allow_module_level=True,
    )


@pytest.fixture(autouse=True)
def clean_factories():
    """Clear node factories before and after each test."""
    clear_node_factories()
    yield
    clear_node_factories()


def _make_node(name: str) -> NodeConfig:
    """Create a minimal NodeConfig (TypedDict) for testing."""
    return NodeConfig(
        name=name,
        task_messages=[{"role": "system", "content": f"You are {name}."}],
    )


def _make_flow_manager(current_node: str = "orchestrator") -> MagicMock:
    """Create a mock FlowManager with state tracking."""
    fm = MagicMock()
    fm.current_node = current_node
    fm.state = {}
    return fm


class TestTransferFunction:
    """Tests for the generic transfer function."""

    @pytest.mark.asyncio
    async def test_transfer_to_registered_target(self):
        """Should successfully transfer to a registered target."""
        register_node_factory(
            "computer_support", lambda: _make_node("computer_support")
        )
        fm = _make_flow_manager("orchestrator")

        result, node = await transfer(
            fm, target="computer_support", reason="WiFi issue"
        )

        assert node is not None
        assert node["name"] == "computer_support"
        assert result["transferred_to"] == "computer_support"
        assert result["reason"] == "WiFi issue"

    @pytest.mark.asyncio
    async def test_transfer_increments_count(self):
        """Should increment the transition count in state."""
        register_node_factory(
            "computer_support", lambda: _make_node("computer_support")
        )
        fm = _make_flow_manager("orchestrator")

        await transfer(fm, target="computer_support", reason="test")
        assert fm.state[_TRANSITION_COUNT_KEY] == 1

        fm.current_node = "computer_support"
        register_node_factory("reception", lambda: _make_node("orchestrator"))
        await transfer(fm, target="reception", reason="done")
        assert fm.state[_TRANSITION_COUNT_KEY] == 2

    @pytest.mark.asyncio
    async def test_transfer_tracks_history(self):
        """Should track transition history in state."""
        register_node_factory(
            "computer_support", lambda: _make_node("computer_support")
        )
        fm = _make_flow_manager("orchestrator")

        await transfer(fm, target="computer_support", reason="WiFi issue")

        history = fm.state[_TRANSITION_HISTORY_KEY]
        assert len(history) == 1
        assert history[0]["from"] == "orchestrator"
        assert history[0]["to"] == "computer_support"
        assert history[0]["reason"] == "WiFi issue"


class TestSelfTransfer:
    """Tests for self-transfer handling."""

    @pytest.mark.asyncio
    async def test_self_transfer_returns_no_node(self):
        """Self-transfer should return None for node (stay in current)."""
        register_node_factory(
            "computer_support", lambda: _make_node("computer_support")
        )
        fm = _make_flow_manager("computer_support")

        result, node = await transfer(fm, target="computer_support", reason="test")

        assert node is None
        assert result.get("stayed_in") == "computer_support"
        assert not result.get("error", False)


class TestUnknownTarget:
    """Tests for unknown target handling."""

    @pytest.mark.asyncio
    async def test_unknown_target_returns_error(self):
        """Transfer to unknown target should return error with available targets."""
        register_node_factory(
            "computer_support", lambda: _make_node("computer_support")
        )
        fm = _make_flow_manager("orchestrator")

        result, node = await transfer(fm, target="nonexistent", reason="test")

        assert node is None
        assert result["error"] is True
        assert "nonexistent" in result["message"]
        assert "computer_support" in result["message"]


class TestLoopProtection:
    """Tests for transition loop protection."""

    @pytest.mark.asyncio
    async def test_loop_protection_activates_at_threshold(self):
        """Should force return to orchestrator after max transitions."""
        register_node_factory("orchestrator", lambda: _make_node("orchestrator"))
        register_node_factory(
            "computer_support", lambda: _make_node("computer_support")
        )
        register_node_factory("billing", lambda: _make_node("billing"))

        fm = _make_flow_manager("computer_support")
        # Simulate having already hit the max
        fm.state[_TRANSITION_COUNT_KEY] = DEFAULT_MAX_TRANSITIONS

        result, node = await transfer(fm, target="billing", reason="loop test")

        # Should force return to orchestrator instead of billing
        assert node is not None
        assert node["name"] == "orchestrator"
        assert result.get("original_target") == "billing"
        assert "loop protection" in result.get("reason", "").lower()

    @pytest.mark.asyncio
    async def test_loop_protection_does_not_activate_before_threshold(self):
        """Should allow transfers below the threshold."""
        register_node_factory(
            "computer_support", lambda: _make_node("computer_support")
        )
        fm = _make_flow_manager("orchestrator")
        fm.state[_TRANSITION_COUNT_KEY] = DEFAULT_MAX_TRANSITIONS - 1

        result, node = await transfer(fm, target="computer_support", reason="test")

        assert node is not None
        assert node["name"] == "computer_support"
        assert result["transferred_to"] == "computer_support"


class TestNodeFactoryRegistry:
    """Tests for the node factory registration system."""

    def test_register_and_get_targets(self):
        """Should register factories and return available targets."""
        register_node_factory("alpha", lambda: _make_node("alpha"))
        register_node_factory("beta", lambda: _make_node("beta"))

        targets = get_available_targets()
        assert targets == ["alpha", "beta"]

    def test_clear_factories(self):
        """Should clear all registered factories."""
        register_node_factory("alpha", lambda: _make_node("alpha"))
        clear_node_factories()
        assert get_available_targets() == []

    @pytest.mark.asyncio
    async def test_factory_creates_correct_node(self):
        """Registered factory should produce the correct NodeConfig."""
        register_node_factory("test_node", lambda: _make_node("test_node"))
        fm = _make_flow_manager("orchestrator")

        result, node = await transfer(fm, target="test_node", reason="test")
        assert node["name"] == "test_node"


class TestTransferMetricsWiring:
    """Tests for metrics collector wiring in transfer()."""

    def _make_collector(self) -> MagicMock:
        """Create a mock MetricsCollector."""
        collector = MagicMock()
        collector.set_agent_node = MagicMock()
        collector.record_agent_transition = MagicMock()
        return collector

    def _make_flow_manager_with_collector(
        self, current_node: str = "orchestrator"
    ) -> tuple:
        """Create a mock FlowManager with a collector in state."""
        collector = self._make_collector()
        fm = MagicMock()
        fm.current_node = current_node
        fm.state = {_COLLECTOR_KEY: collector}
        return fm, collector

    @pytest.mark.asyncio
    async def test_successful_transfer_sets_agent_node(self):
        """Should call collector.set_agent_node(target) on successful transfer."""
        register_node_factory(
            "computer_support", lambda: _make_node("computer_support")
        )
        fm, collector = self._make_flow_manager_with_collector("orchestrator")

        await transfer(fm, target="computer_support", reason="WiFi issue")

        collector.set_agent_node.assert_called_once_with("computer_support")

    @pytest.mark.asyncio
    async def test_successful_transfer_records_transition(self):
        """Should call collector.record_agent_transition() on successful transfer."""
        register_node_factory(
            "computer_support", lambda: _make_node("computer_support")
        )
        fm, collector = self._make_flow_manager_with_collector("orchestrator")

        await transfer(fm, target="computer_support", reason="WiFi issue")

        collector.record_agent_transition.assert_called_once()
        call_kwargs = collector.record_agent_transition.call_args[1]
        assert call_kwargs["from_node"] == "orchestrator"
        assert call_kwargs["to_node"] == "computer_support"
        assert call_kwargs["reason"] == "WiFi issue"
        assert "transition_latency_ms" in call_kwargs
        assert isinstance(call_kwargs["transition_latency_ms"], float)
        assert call_kwargs["transition_latency_ms"] >= 0
        # No loop_protection on normal transfer
        assert "loop_protection" not in call_kwargs or not call_kwargs.get(
            "loop_protection"
        )

    @pytest.mark.asyncio
    async def test_no_collector_does_not_crash(self):
        """Should not crash when collector is None in state."""
        register_node_factory(
            "computer_support", lambda: _make_node("computer_support")
        )
        fm = _make_flow_manager("orchestrator")
        # No collector in state

        result, node = await transfer(
            fm, target="computer_support", reason="WiFi issue"
        )

        assert node is not None
        assert result["transferred_to"] == "computer_support"

    @pytest.mark.asyncio
    async def test_self_transfer_does_not_record_transition(self):
        """Self-transfer should not call record_agent_transition."""
        register_node_factory(
            "computer_support", lambda: _make_node("computer_support")
        )
        fm, collector = self._make_flow_manager_with_collector("computer_support")

        result, node = await transfer(fm, target="computer_support", reason="stay here")

        assert node is None
        collector.set_agent_node.assert_not_called()
        collector.record_agent_transition.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_target_does_not_record_transition(self):
        """Unknown target should not call record_agent_transition."""
        register_node_factory(
            "computer_support", lambda: _make_node("computer_support")
        )
        fm, collector = self._make_flow_manager_with_collector("orchestrator")

        result, node = await transfer(fm, target="nonexistent", reason="test")

        assert node is None
        collector.set_agent_node.assert_not_called()
        collector.record_agent_transition.assert_not_called()

    @pytest.mark.asyncio
    async def test_loop_protection_records_with_flag(self):
        """Loop protection should call record_agent_transition with loop_protection=True."""
        register_node_factory("orchestrator", lambda: _make_node("orchestrator"))
        register_node_factory("billing", lambda: _make_node("billing"))
        fm, collector = self._make_flow_manager_with_collector("computer_support")
        fm.state[_TRANSITION_COUNT_KEY] = DEFAULT_MAX_TRANSITIONS  # Next will exceed

        await transfer(fm, target="billing", reason="loop test")

        collector.set_agent_node.assert_called_once_with("orchestrator")
        collector.record_agent_transition.assert_called_once()
        call_kwargs = collector.record_agent_transition.call_args[1]
        assert call_kwargs["from_node"] == "computer_support"
        assert call_kwargs["to_node"] == "orchestrator"
        assert call_kwargs["loop_protection"] is True
        assert "transition_latency_ms" in call_kwargs

    @pytest.mark.asyncio
    async def test_loop_protection_fallback_records_with_flag(self):
        """Loop protection without orchestrator factory should still record."""
        # No orchestrator or reception factory -- last resort path
        fm, collector = self._make_flow_manager_with_collector("specialist")
        fm.state[_TRANSITION_COUNT_KEY] = DEFAULT_MAX_TRANSITIONS

        result, node = await transfer(fm, target="billing", reason="loop test")

        assert node is None
        assert result["error"] is True
        # Should still record the loop protection activation
        collector.record_agent_transition.assert_called_once()
        call_kwargs = collector.record_agent_transition.call_args[1]
        assert call_kwargs["loop_protection"] is True

    @pytest.mark.asyncio
    async def test_transition_latency_is_positive(self):
        """Transition latency should be a positive number."""
        register_node_factory("billing", lambda: _make_node("billing"))
        fm, collector = self._make_flow_manager_with_collector("orchestrator")

        await transfer(fm, target="billing", reason="billing question")

        call_kwargs = collector.record_agent_transition.call_args[1]
        assert call_kwargs["transition_latency_ms"] > 0

    @pytest.mark.asyncio
    async def test_collector_exception_does_not_break_transfer(self):
        """If collector throws, transfer should still succeed."""
        register_node_factory(
            "computer_support", lambda: _make_node("computer_support")
        )
        fm, collector = self._make_flow_manager_with_collector("orchestrator")
        collector.set_agent_node.side_effect = RuntimeError("metrics broken")

        result, node = await transfer(
            fm, target="computer_support", reason="WiFi issue"
        )

        # Transfer still succeeds despite collector error
        assert node is not None
        assert result["transferred_to"] == "computer_support"


class TestTransitionHardening:
    """Hardening tests for rapid transitions, state isolation, and failure modes."""

    def _make_collector(self) -> MagicMock:
        """Create a mock MetricsCollector."""
        collector = MagicMock()
        collector.set_agent_node = MagicMock()
        collector.record_agent_transition = MagicMock()
        return collector

    @pytest.mark.asyncio
    async def test_rapid_back_and_forth_20_transitions(self):
        """Stress test: 20 rapid back-and-forth transitions without crashes."""
        register_node_factory("orchestrator", lambda: _make_node("orchestrator"))
        register_node_factory(
            "computer_support", lambda: _make_node("computer_support")
        )

        collector = self._make_collector()
        fm = MagicMock()
        fm.state = {_COLLECTOR_KEY: collector}

        targets = ["computer_support", "orchestrator"] * 10  # 20 transitions
        for i, target in enumerate(targets):
            fm.current_node = (
                "orchestrator" if target == "computer_support" else "computer_support"
            )
            result, node = await transfer(fm, target=target, reason=f"transition {i}")
            # First 10 should succeed (DEFAULT_MAX_TRANSITIONS=10)
            if i < DEFAULT_MAX_TRANSITIONS:
                assert node is not None, f"Transition {i} should succeed"
                assert result.get("transferred_to") == target
            else:
                # Loop protection should redirect to orchestrator
                if node is not None:
                    assert node["name"] == "orchestrator"

        # Verify metrics were recorded for all transitions
        assert collector.record_agent_transition.call_count == 20

    @pytest.mark.asyncio
    async def test_cross_call_state_isolation(self):
        """Two independent flow managers must not share transition state."""
        register_node_factory("orchestrator", lambda: _make_node("orchestrator"))
        register_node_factory("billing", lambda: _make_node("billing"))

        collector1 = self._make_collector()
        collector2 = self._make_collector()

        fm1 = MagicMock()
        fm1.current_node = "orchestrator"
        fm1.state = {_COLLECTOR_KEY: collector1}

        fm2 = MagicMock()
        fm2.current_node = "orchestrator"
        fm2.state = {_COLLECTOR_KEY: collector2}

        # Transfer on fm1
        await transfer(fm1, target="billing", reason="call 1")
        assert fm1.state[_TRANSITION_COUNT_KEY] == 1

        # fm2 should still be at 0
        assert _TRANSITION_COUNT_KEY not in fm2.state

        # Transfer on fm2
        await transfer(fm2, target="billing", reason="call 2")
        assert fm2.state[_TRANSITION_COUNT_KEY] == 1
        assert fm1.state[_TRANSITION_COUNT_KEY] == 1  # unchanged

        # Collectors are independent
        collector1.set_agent_node.assert_called_once_with("billing")
        collector2.set_agent_node.assert_called_once_with("billing")

    @pytest.mark.asyncio
    async def test_transition_after_loop_protection_still_works(self):
        """After loop protection fires, new calls (fresh state) should work normally."""
        register_node_factory("orchestrator", lambda: _make_node("orchestrator"))
        register_node_factory("billing", lambda: _make_node("billing"))

        # First: exhaust loop protection
        collector = self._make_collector()
        fm = MagicMock()
        fm.current_node = "billing"
        fm.state = {
            _COLLECTOR_KEY: collector,
            _TRANSITION_COUNT_KEY: DEFAULT_MAX_TRANSITIONS,
        }

        result, node = await transfer(fm, target="billing", reason="loop")
        assert node is not None
        assert "loop protection" in result.get("reason", "").lower()

        # New call (fresh state) should work fine
        fm2 = MagicMock()
        fm2.current_node = "orchestrator"
        fm2.state = {_COLLECTOR_KEY: self._make_collector()}

        result, node = await transfer(fm2, target="billing", reason="fresh call")
        assert node is not None
        assert result["transferred_to"] == "billing"
        assert fm2.state[_TRANSITION_COUNT_KEY] == 1

    @pytest.mark.asyncio
    async def test_all_error_paths_record_metrics_or_skip_safely(self):
        """Each error path (self, unknown, loop) should not leave collector in bad state."""
        register_node_factory("orchestrator", lambda: _make_node("orchestrator"))
        register_node_factory("billing", lambda: _make_node("billing"))

        collector = self._make_collector()
        fm = MagicMock()
        fm.current_node = "billing"
        fm.state = {_COLLECTOR_KEY: collector}

        # Self-transfer: no record
        await transfer(fm, target="billing", reason="self")
        assert collector.record_agent_transition.call_count == 0

        # Unknown target: no record
        await transfer(fm, target="nonexistent", reason="unknown")
        assert collector.record_agent_transition.call_count == 0

        # Successful transfer: records
        fm.current_node = "billing"
        await transfer(fm, target="orchestrator", reason="success")
        assert collector.record_agent_transition.call_count == 1

        # After all paths, collector should still be usable
        collector.set_agent_node("test")
        collector.set_agent_node.assert_called_with("test")

    @pytest.mark.asyncio
    async def test_transition_history_grows_correctly(self):
        """History should accumulate across transitions for debugging."""
        register_node_factory("orchestrator", lambda: _make_node("orchestrator"))
        register_node_factory("billing", lambda: _make_node("billing"))
        register_node_factory(
            "computer_support", lambda: _make_node("computer_support")
        )

        fm = MagicMock()
        fm.current_node = "orchestrator"
        fm.state = {}

        await transfer(fm, target="billing", reason="billing q")
        fm.current_node = "billing"
        await transfer(fm, target="computer_support", reason="tech q")
        fm.current_node = "computer_support"
        await transfer(fm, target="orchestrator", reason="done")

        history = fm.state[_TRANSITION_HISTORY_KEY]
        assert len(history) == 3
        assert history[0]["from"] == "orchestrator"
        assert history[0]["to"] == "billing"
        assert history[1]["from"] == "billing"
        assert history[1]["to"] == "computer_support"
        assert history[2]["from"] == "computer_support"
        assert history[2]["to"] == "orchestrator"
