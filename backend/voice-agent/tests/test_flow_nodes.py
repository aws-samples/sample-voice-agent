"""Unit tests for flow node definitions (dynamic design).

Tests that node creation functions produce correct NodeConfig dicts
with the expected structure. Specialist nodes are created dynamically
from Agent Card metadata, not from hard-coded definitions.

Note: NodeConfig is a TypedDict -- fields accessed via dict syntax.

Run with: .venv/bin/python -m pytest tests/test_flow_nodes.py -v
"""

from unittest.mock import MagicMock

import pytest

try:
    from pipecat_flows import (
        ContextStrategy,
        ContextStrategyConfig,
        NodeConfig,
    )

    from app.flows.nodes.orchestrator import create_orchestrator_node
    from app.flows.nodes.specialist import create_specialist_node, slugify_service_name
    from app.flows.context import (
        get_summary_prompt,
        GENERIC_SUMMARY_PROMPT,
        ORCHESTRATOR_SUMMARY_PROMPT,
        _DOMAIN_SUMMARY_TEMPLATE,
    )
except ImportError:
    pytest.skip(
        "Container-only dependencies not available (pipecat-flows)",
        allow_module_level=True,
    )


# =============================================================================
# Orchestrator Node Tests
# =============================================================================


class TestOrchestratorNode:
    """Tests for the orchestrator/reception node."""

    def test_creates_valid_node_config(self):
        """Should return a dict with required NodeConfig keys."""
        node = create_orchestrator_node()
        assert isinstance(node, dict)
        assert "name" in node

    def test_node_name_is_orchestrator(self):
        """Node name should be 'orchestrator'."""
        node = create_orchestrator_node()
        assert node["name"] == "orchestrator"

    def test_has_role_messages(self):
        """Should have role messages defining the receptionist persona."""
        node = create_orchestrator_node()
        assert node.get("role_messages")
        assert len(node["role_messages"]) >= 1
        assert node["role_messages"][0]["role"] == "system"
        assert "receptionist" in node["role_messages"][0]["content"].lower()

    def test_has_task_messages(self):
        """Should have task messages with routing instructions."""
        node = create_orchestrator_node()
        assert node.get("task_messages")
        assert len(node["task_messages"]) >= 1

    def test_has_transfer_function(self):
        """Should include the transfer function."""
        node = create_orchestrator_node()
        assert node.get("functions")
        func_names = [
            getattr(f, "__name__", getattr(f, "name", str(f)))
            for f in node["functions"]
        ]
        assert "transfer" in func_names

    def test_first_entry_has_greeting_pre_action(self):
        """First entry should have a greeting TTS pre-action."""
        node = create_orchestrator_node(is_return=False)
        assert node.get("pre_actions")
        tts_actions = [a for a in node["pre_actions"] if a.get("type") == "tts_say"]
        assert len(tts_actions) >= 1
        text = tts_actions[0]["text"].lower()
        assert "hello" in text or "thank you" in text

    def test_return_entry_has_anything_else_pre_action(self):
        """Return entry should ask 'anything else?' via TTS."""
        node = create_orchestrator_node(is_return=True)
        assert node.get("pre_actions")
        tts_actions = [a for a in node["pre_actions"] if a.get("type") == "tts_say"]
        assert len(tts_actions) >= 1
        assert "anything else" in tts_actions[0]["text"].lower()

    def test_first_entry_has_no_context_strategy(self):
        """First entry should not have a context strategy (uses default)."""
        node = create_orchestrator_node(is_return=False)
        assert node.get("context_strategy") is None

    def test_return_entry_has_reset_with_summary(self):
        """Return entry should use RESET_WITH_SUMMARY context strategy."""
        node = create_orchestrator_node(is_return=True)
        cs = node.get("context_strategy")
        assert cs is not None
        assert cs.strategy == ContextStrategy.RESET_WITH_SUMMARY
        assert cs.summary_prompt

    def test_dynamic_agent_descriptions_in_task(self):
        """Task message should include discovered agent descriptions."""
        descriptions = {
            "kb_agent": "Searches knowledge base for docs",
            "crm_agent": "Customer relationship management",
        }
        node = create_orchestrator_node(agent_descriptions=descriptions)
        task_content = node["task_messages"][0]["content"]
        assert "kb_agent" in task_content
        assert "crm_agent" in task_content
        assert "knowledge base" in task_content.lower()

    def test_no_agents_uses_fallback_task(self):
        """When no agents discovered, should use fallback task message."""
        node = create_orchestrator_node(agent_descriptions=None)
        task_content = node["task_messages"][0]["content"]
        # Fallback should mention no specialists
        assert (
            "no specialist" in task_content.lower()
            or "transfer" in task_content.lower()
        )

    def test_empty_agents_uses_fallback_task(self):
        """Empty agent dict should use fallback task message."""
        node = create_orchestrator_node(agent_descriptions={})
        task_content = node["task_messages"][0]["content"]
        assert "no specialist" in task_content.lower()


# =============================================================================
# Generic Specialist Node Tests
# =============================================================================


class TestSpecialistNode:
    """Tests for the generic specialist node created from Agent Card data."""

    def test_creates_valid_node_config(self):
        """Should return a dict with required NodeConfig keys."""
        node = create_specialist_node(
            node_name="kb_agent",
            agent_name="Knowledge Base Agent",
            agent_description="Searches enterprise knowledge base.",
        )
        assert isinstance(node, dict)
        assert "name" in node

    def test_node_name_from_argument(self):
        """Node name should match the provided node_name."""
        node = create_specialist_node(
            node_name="crm_agent",
            agent_name="CRM Agent",
            agent_description="Customer management.",
        )
        assert node["name"] == "crm_agent"

    def test_role_includes_agent_description(self):
        """Role message should incorporate the agent's description."""
        node = create_specialist_node(
            node_name="kb_agent",
            agent_name="Knowledge Base Agent",
            agent_description="Searches enterprise knowledge base for product info.",
        )
        content = node["role_messages"][0]["content"]
        assert "knowledge base" in content.lower()

    def test_has_transfer_function(self):
        """Should include the transfer function."""
        node = create_specialist_node(
            node_name="kb_agent",
            agent_name="KB Agent",
            agent_description="Searches KB.",
        )
        func_names = [
            getattr(f, "__name__", getattr(f, "name", str(f)))
            for f in node["functions"]
        ]
        assert "transfer" in func_names

    def test_includes_a2a_functions(self):
        """Should include A2A functions when provided."""
        mock_fn = MagicMock()
        mock_fn.__name__ = "search_knowledge_base"
        node = create_specialist_node(
            node_name="kb_agent",
            agent_name="KB Agent",
            agent_description="Searches KB.",
            a2a_functions=[mock_fn],
        )
        assert len(node["functions"]) >= 2  # transfer + search_knowledge_base

    def test_no_a2a_functions_when_none(self):
        """Should only have transfer when no A2A functions provided."""
        node = create_specialist_node(
            node_name="kb_agent",
            agent_name="KB Agent",
            agent_description="Searches KB.",
            a2a_functions=None,
        )
        assert len(node["functions"]) == 1  # just transfer

    def test_has_transition_pre_action(self):
        """Should have a TTS pre-action for the transition phrase."""
        node = create_specialist_node(
            node_name="crm_agent",
            agent_name="CRM Agent",
            agent_description="Customer management.",
        )
        assert node.get("pre_actions")
        tts_actions = [a for a in node["pre_actions"] if a.get("type") == "tts_say"]
        assert len(tts_actions) >= 1
        # Brief transition phrase -- avoids double-introduction with LLM greeting
        assert "moment" in tts_actions[0]["text"].lower()

    def test_has_reset_with_summary(self):
        """Should use RESET_WITH_SUMMARY context strategy."""
        node = create_specialist_node(
            node_name="kb_agent",
            agent_name="KB Agent",
            agent_description="Searches KB.",
        )
        cs = node.get("context_strategy")
        assert cs is not None
        assert cs.strategy == ContextStrategy.RESET_WITH_SUMMARY
        assert cs.summary_prompt

    def test_different_agents_produce_different_nodes(self):
        """Two agents should produce nodes with different names and personas."""
        node_a = create_specialist_node(
            node_name="kb_agent",
            agent_name="Knowledge Base Agent",
            agent_description="Searches enterprise knowledge base.",
        )
        node_b = create_specialist_node(
            node_name="crm_agent",
            agent_name="CRM Agent",
            agent_description="Customer relationship management.",
        )
        assert node_a["name"] != node_b["name"]
        assert (
            node_a["role_messages"][0]["content"]
            != node_b["role_messages"][0]["content"]
        )


# =============================================================================
# Slugify Tests
# =============================================================================


class TestSlugifyServiceName:
    """Tests for CloudMap service name to node name conversion."""

    def test_hyphen_to_underscore(self):
        assert slugify_service_name("crm-agent") == "crm_agent"

    def test_multi_hyphen(self):
        assert slugify_service_name("knowledge-base-agent") == "knowledge_base_agent"

    def test_already_clean(self):
        assert slugify_service_name("kb_agent") == "kb_agent"

    def test_uppercase(self):
        assert slugify_service_name("CRM-Agent") == "crm_agent"

    def test_no_hyphens(self):
        assert slugify_service_name("agent") == "agent"


# =============================================================================
# Summary Prompt Tests
# =============================================================================


class TestSummaryPrompts:
    """Tests for summary prompt retrieval."""

    def test_generic_prompt_for_specialist(self):
        """Specialist nodes without agent_description should get the generic summary prompt."""
        prompt = get_summary_prompt("kb_agent")
        assert prompt == GENERIC_SUMMARY_PROMPT

    def test_orchestrator_prompt_for_orchestrator(self):
        """Orchestrator should get its specific prompt."""
        prompt = get_summary_prompt("orchestrator")
        assert prompt == ORCHESTRATOR_SUMMARY_PROMPT

    def test_reception_gets_orchestrator_prompt(self):
        """'reception' alias should get orchestrator prompt."""
        prompt = get_summary_prompt("reception")
        assert prompt == ORCHESTRATOR_SUMMARY_PROMPT

    def test_empty_name_gets_generic(self):
        """Empty name should get generic prompt."""
        prompt = get_summary_prompt("")
        assert prompt == GENERIC_SUMMARY_PROMPT

    def test_unknown_name_gets_generic(self):
        """Unknown name should get generic prompt."""
        prompt = get_summary_prompt("nonexistent")
        assert prompt == GENERIC_SUMMARY_PROMPT

    def test_prompts_mention_factual_format(self):
        """Both prompts should mention factual bullet-point format."""
        assert "bullet" in GENERIC_SUMMARY_PROMPT.lower()
        assert "bullet" in ORCHESTRATOR_SUMMARY_PROMPT.lower()


# =============================================================================
# Domain-Aware Summary Prompt Tests
# =============================================================================


class TestDomainAwareSummaryPrompts:
    """Tests for domain-aware summary prompts using Agent Card metadata."""

    def test_with_agent_description_returns_domain_prompt(self):
        """When agent_description is provided, should return a domain-aware prompt."""
        desc = "Searches the enterprise knowledge base for technical documentation."
        prompt = get_summary_prompt("kb_agent", agent_description=desc)
        assert prompt != GENERIC_SUMMARY_PROMPT
        assert desc in prompt

    def test_domain_prompt_mentions_focus_shift(self):
        """Domain-aware prompt should mention shifting focus."""
        prompt = get_summary_prompt(
            "crm_agent",
            agent_description="Manages customer accounts and support cases.",
        )
        assert "shifting focus" in prompt.lower()

    def test_domain_prompt_mentions_factual_format(self):
        """Domain-aware prompt should mention factual bullet-point format."""
        prompt = get_summary_prompt(
            "kb_agent",
            agent_description="Knowledge base search.",
        )
        assert "bullet" in prompt.lower()

    def test_domain_prompt_mentions_identifiers(self):
        """Domain-aware prompt should ask for identifiers."""
        prompt = get_summary_prompt(
            "kb_agent",
            agent_description="Searches technical docs.",
        )
        assert "identifiers" in prompt.lower()

    def test_orchestrator_ignores_agent_description(self):
        """Orchestrator should always get orchestrator prompt, even with description."""
        prompt = get_summary_prompt(
            "orchestrator",
            agent_description="Some description that should be ignored.",
        )
        assert prompt == ORCHESTRATOR_SUMMARY_PROMPT

    def test_reception_ignores_agent_description(self):
        """Reception should always get orchestrator prompt, even with description."""
        prompt = get_summary_prompt(
            "reception",
            agent_description="Some description that should be ignored.",
        )
        assert prompt == ORCHESTRATOR_SUMMARY_PROMPT

    def test_none_description_falls_back_to_generic(self):
        """None description should fall back to generic prompt."""
        prompt = get_summary_prompt("kb_agent", agent_description=None)
        assert prompt == GENERIC_SUMMARY_PROMPT

    def test_empty_description_falls_back_to_generic(self):
        """Empty string description should fall back to generic prompt."""
        prompt = get_summary_prompt("kb_agent", agent_description="")
        assert prompt == GENERIC_SUMMARY_PROMPT

    def test_domain_template_has_placeholder(self):
        """The domain template should use {agent_description} placeholder."""
        assert "{agent_description}" in _DOMAIN_SUMMARY_TEMPLATE

    def test_different_descriptions_produce_different_prompts(self):
        """Different agent descriptions should produce different prompts."""
        prompt_a = get_summary_prompt(
            "kb_agent",
            agent_description="Searches the knowledge base.",
        )
        prompt_b = get_summary_prompt(
            "crm_agent",
            agent_description="Manages customer relationships.",
        )
        assert prompt_a != prompt_b

    def test_specialist_node_uses_domain_prompt(self):
        """create_specialist_node should pass agent_description to get_summary_prompt."""
        node = create_specialist_node(
            node_name="kb_agent",
            agent_name="KB Agent",
            agent_description="Searches the enterprise knowledge base for documentation.",
        )
        cs = node.get("context_strategy")
        assert cs is not None
        assert cs.strategy == ContextStrategy.RESET_WITH_SUMMARY
        # The summary prompt should be domain-aware, not generic
        assert cs.summary_prompt != GENERIC_SUMMARY_PROMPT
        assert "knowledge base" in cs.summary_prompt.lower()

    def test_specialist_node_prompt_contains_description(self):
        """Specialist node's summary prompt should contain the agent description."""
        description = "Manages customer accounts and support tickets."
        node = create_specialist_node(
            node_name="crm_agent",
            agent_name="CRM Agent",
            agent_description=description,
        )
        cs = node.get("context_strategy")
        assert description in cs.summary_prompt
