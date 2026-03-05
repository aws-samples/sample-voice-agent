"""Tests for dependency gating in multi-agent flows.

Tests the provides/requires tag parsing, state tracking, transfer
gating, and redirect logic.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.flows.dependencies import (
    parse_skill_tags,
    aggregate_agent_tags,
    mark_dependency_satisfied,
    get_satisfied_dependencies,
    check_transfer_requirements,
    set_pending_target,
    pop_pending_target,
    SATISFIED_DEPS_KEY,
    PENDING_TARGET_KEY,
    PENDING_REASON_KEY,
)


# =============================================================================
# Tag parsing
# =============================================================================


class TestParseSkillTags:
    """Test parse_skill_tags()."""

    def test_empty_tags(self):
        provides, requires = parse_skill_tags([])
        assert provides == set()
        assert requires == set()

    def test_provides_tag(self):
        provides, requires = parse_skill_tags(["provides:customer_id"])
        assert provides == {"customer_id"}
        assert requires == set()

    def test_requires_tag(self):
        provides, requires = parse_skill_tags(["requires:customer_id"])
        assert provides == set()
        assert requires == {"customer_id"}

    def test_mixed_tags(self):
        provides, requires = parse_skill_tags(
            [
                "provides:customer_id",
                "requires:appointment_id",
                "crm",  # unrelated tag, ignored
            ]
        )
        assert provides == {"customer_id"}
        assert requires == {"appointment_id"}

    def test_multiple_provides(self):
        provides, requires = parse_skill_tags(
            [
                "provides:customer_id",
                "provides:account_verified",
            ]
        )
        assert provides == {"customer_id", "account_verified"}

    def test_case_insensitive(self):
        provides, _ = parse_skill_tags(["Provides:Customer_ID"])
        assert provides == {"customer_id"}

    def test_whitespace_handling(self):
        provides, _ = parse_skill_tags(["  provides:customer_id  "])
        assert provides == {"customer_id"}

    def test_empty_key_ignored(self):
        provides, requires = parse_skill_tags(["provides:", "requires:"])
        assert provides == set()
        assert requires == set()


class TestAggregateAgentTags:
    """Test aggregate_agent_tags()."""

    def test_empty_skills(self):
        provides, requires = aggregate_agent_tags([])
        assert provides == set()
        assert requires == set()

    def test_single_skill(self):
        provides, requires = aggregate_agent_tags(
            [
                ["provides:customer_id"],
            ]
        )
        assert provides == {"customer_id"}

    def test_multiple_skills_aggregate(self):
        provides, requires = aggregate_agent_tags(
            [
                ["provides:customer_id"],  # lookup_customer
                ["requires:customer_id"],  # create_support_case
                ["requires:customer_id"],  # add_case_note
            ]
        )
        assert provides == {"customer_id"}
        assert requires == {"customer_id"}

    def test_appointment_agent_tags(self):
        """Appointment agent: some skills require, some don't."""
        provides, requires = aggregate_agent_tags(
            [
                [],  # check_availability
                ["requires:customer_id"],  # book_appointment
                [],  # get_appointment
                ["requires:customer_id"],  # cancel_appointment
                ["requires:customer_id"],  # reschedule_appointment
            ]
        )
        assert provides == set()
        assert requires == {"customer_id"}


# =============================================================================
# State tracking
# =============================================================================


class TestDependencyState:
    """Test dependency state management in flow_manager.state."""

    def test_mark_satisfied(self):
        state = {}
        mark_dependency_satisfied(state, "customer_id")
        assert "customer_id" in state[SATISFIED_DEPS_KEY]

    def test_mark_multiple(self):
        state = {}
        mark_dependency_satisfied(state, "customer_id")
        mark_dependency_satisfied(state, "account_verified")
        assert state[SATISFIED_DEPS_KEY] == {"customer_id", "account_verified"}

    def test_idempotent(self):
        state = {}
        mark_dependency_satisfied(state, "customer_id")
        mark_dependency_satisfied(state, "customer_id")
        assert state[SATISFIED_DEPS_KEY] == {"customer_id"}

    def test_get_empty(self):
        assert get_satisfied_dependencies({}) == set()

    def test_get_populated(self):
        state = {SATISFIED_DEPS_KEY: {"customer_id"}}
        assert get_satisfied_dependencies(state) == {"customer_id"}


# =============================================================================
# Transfer requirement checking
# =============================================================================


class TestCheckTransferRequirements:
    """Test check_transfer_requirements()."""

    def test_no_requirements(self):
        result = check_transfer_requirements(
            target_name="knowledge_base",
            target_requires=set(),
            satisfied=set(),
            provider_map={},
        )
        assert result is None

    def test_requirements_satisfied(self):
        result = check_transfer_requirements(
            target_name="appointment",
            target_requires={"customer_id"},
            satisfied={"customer_id"},
            provider_map={"customer_id": "crm"},
        )
        assert result is None

    def test_requirements_unsatisfied_with_provider(self):
        result = check_transfer_requirements(
            target_name="appointment",
            target_requires={"customer_id"},
            satisfied=set(),
            provider_map={"customer_id": "crm"},
        )
        assert result is not None
        assert result["redirect_to"] == "crm"
        assert "customer_id" in result["missing"]
        assert result["original_target"] == "appointment"

    def test_requirements_unsatisfied_no_provider(self):
        """When no provider exists, return None (allow transfer, rely on self-gate)."""
        result = check_transfer_requirements(
            target_name="appointment",
            target_requires={"customer_id"},
            satisfied=set(),
            provider_map={},  # No provider registered
        )
        assert result is None

    def test_partial_satisfaction(self):
        """Some deps satisfied, some not."""
        result = check_transfer_requirements(
            target_name="appointment",
            target_requires={"customer_id", "account_verified"},
            satisfied={"account_verified"},
            provider_map={"customer_id": "crm"},
        )
        assert result is not None
        assert result["redirect_to"] == "crm"
        assert "customer_id" in result["missing"]


# =============================================================================
# Pending target
# =============================================================================


class TestPendingTarget:
    """Test pending target storage for dependency redirects."""

    def test_set_and_pop(self):
        state = {}
        set_pending_target(state, "appointment", "schedule repair")
        result = pop_pending_target(state)
        assert result == ("appointment", "schedule repair")

    def test_pop_clears_state(self):
        state = {}
        set_pending_target(state, "appointment", "schedule repair")
        pop_pending_target(state)
        assert PENDING_TARGET_KEY not in state
        assert PENDING_REASON_KEY not in state

    def test_pop_empty_returns_none(self):
        assert pop_pending_target({}) is None

    def test_overwrite(self):
        state = {}
        set_pending_target(state, "appointment", "first reason")
        set_pending_target(state, "crm", "second reason")
        result = pop_pending_target(state)
        assert result == ("crm", "second reason")


# =============================================================================
# Integration: transfer() with dependency gating
# =============================================================================


class TestTransferDependencyGating:
    """Test that transfer() redirects when dependencies are unsatisfied."""

    @pytest.fixture(autouse=True)
    def setup_factories(self):
        """Register mock node factories."""
        from app.flows.transitions import register_node_factory, clear_node_factories

        clear_node_factories()

        # Mock node factories
        self.mock_crm_node = {"name": "crm", "role_messages": [], "task_messages": []}
        self.mock_appt_node = {
            "name": "appointment",
            "role_messages": [],
            "task_messages": [],
        }
        self.mock_orch_node = {
            "name": "orchestrator",
            "role_messages": [],
            "task_messages": [],
        }

        register_node_factory("crm", lambda: self.mock_crm_node)
        register_node_factory("appointment", lambda: self.mock_appt_node)
        register_node_factory("orchestrator", lambda: self.mock_orch_node)
        register_node_factory("reception", lambda: self.mock_orch_node)

        yield

        clear_node_factories()

    def _make_flow_manager(
        self, requirements_map=None, provider_map=None, satisfied=None
    ):
        """Create a mock flow_manager with dependency state."""
        fm = MagicMock()
        fm.current_node = "knowledge_base"
        fm.state = {
            "_requirements_map": requirements_map or {},
            "_provider_map": provider_map or {},
        }
        if satisfied:
            fm.state[SATISFIED_DEPS_KEY] = satisfied
        return fm

    @pytest.mark.asyncio
    async def test_transfer_to_appointment_blocked(self):
        """Transfer to appointment should redirect to CRM when customer_id missing."""
        fm = self._make_flow_manager(
            requirements_map={"appointment": {"customer_id"}},
            provider_map={"customer_id": "crm"},
        )

        from app.flows.transitions import transfer

        result, node = await transfer(fm, "appointment", "schedule repair")

        # Should redirect to CRM
        assert result["transferred_to"] == "crm"
        assert node == self.mock_crm_node

        # Original target should be stored as pending
        assert fm.state[PENDING_TARGET_KEY] == "appointment"

    @pytest.mark.asyncio
    async def test_transfer_to_appointment_allowed(self):
        """Transfer to appointment should proceed when customer_id is satisfied."""
        fm = self._make_flow_manager(
            requirements_map={"appointment": {"customer_id"}},
            provider_map={"customer_id": "crm"},
            satisfied={"customer_id"},
        )

        from app.flows.transitions import transfer

        result, node = await transfer(fm, "appointment", "schedule repair")

        # Should go directly to appointment
        assert result["transferred_to"] == "appointment"
        assert node == self.mock_appt_node

    @pytest.mark.asyncio
    async def test_transfer_to_crm_no_requirements(self):
        """Transfer to CRM should always succeed (no requirements)."""
        fm = self._make_flow_manager(
            requirements_map={"appointment": {"customer_id"}},
            provider_map={"customer_id": "crm"},
        )

        from app.flows.transitions import transfer

        result, node = await transfer(fm, "crm", "look up customer")

        assert result["transferred_to"] == "crm"
        assert node == self.mock_crm_node

    @pytest.mark.asyncio
    async def test_transfer_no_dependency_config(self):
        """Transfer works normally when no dependency config exists."""
        fm = self._make_flow_manager()

        from app.flows.transitions import transfer

        result, node = await transfer(fm, "appointment", "schedule repair")

        assert result["transferred_to"] == "appointment"
        assert node == self.mock_appt_node
