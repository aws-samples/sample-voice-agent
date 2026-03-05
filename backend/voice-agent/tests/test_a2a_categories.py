"""Tests for A2A agent-to-category mapping."""

import pytest

try:
    from app.a2a.categories import resolve_tool_category
    from app.tools.schema import ToolCategory
except ImportError:
    pytest.skip(
        "Container-only dependencies not available (structlog)", allow_module_level=True
    )


class TestResolveToolCategory:
    """Tests for resolve_tool_category."""

    # --- Knowledge Base agent ---

    def test_kb_agent_display_name(self):
        assert (
            resolve_tool_category("Knowledge Base Agent") == ToolCategory.KNOWLEDGE_BASE
        )

    def test_kb_agent_service_name(self):
        assert resolve_tool_category("kb-agent") == ToolCategory.KNOWLEDGE_BASE

    def test_kb_agent_underscore(self):
        assert resolve_tool_category("kb_agent") == ToolCategory.KNOWLEDGE_BASE

    def test_kb_agent_mixed_case(self):
        assert (
            resolve_tool_category("KNOWLEDGE BASE AGENT") == ToolCategory.KNOWLEDGE_BASE
        )

    # --- CRM agent ---

    def test_crm_agent_display_name(self):
        assert resolve_tool_category("CRM Agent") == ToolCategory.CRM

    def test_crm_agent_service_name(self):
        assert resolve_tool_category("crm-agent") == ToolCategory.CRM

    def test_crm_agent_lowercase(self):
        assert resolve_tool_category("crm") == ToolCategory.CRM

    # --- Appointment / scheduling agent ---

    def test_appointment_agent_display_name(self):
        assert resolve_tool_category("Appointment Agent") == ToolCategory.APPOINTMENT

    def test_appointment_agent_service_name(self):
        assert resolve_tool_category("appointment-agent") == ToolCategory.APPOINTMENT

    def test_scheduling_agent(self):
        assert resolve_tool_category("scheduling-agent") == ToolCategory.APPOINTMENT

    # --- Fallback ---

    def test_unknown_agent_falls_back_to_system(self):
        assert resolve_tool_category("SomeBrandNewAgent") == ToolCategory.SYSTEM

    def test_empty_string_falls_back_to_system(self):
        assert resolve_tool_category("") == ToolCategory.SYSTEM

    def test_whitespace_only_falls_back_to_system(self):
        assert resolve_tool_category("   ") == ToolCategory.SYSTEM

    # --- Value strings match ToolCategory.value ---

    def test_kb_value_string(self):
        cat = resolve_tool_category("kb-agent")
        assert cat.value == "knowledge_base"

    def test_crm_value_string(self):
        cat = resolve_tool_category("crm-agent")
        assert cat.value == "crm"

    def test_appointment_value_string(self):
        cat = resolve_tool_category("appointment-agent")
        assert cat.value == "appointment"

    def test_fallback_value_string(self):
        cat = resolve_tool_category("unknown-agent")
        assert cat.value == "system"
