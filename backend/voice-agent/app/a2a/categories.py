"""A2A agent-to-category mapping.

Resolves a meaningful ToolCategory from agent metadata so that CloudWatch
metrics, structured logs, and filler phrases can distinguish KB operations
from CRM operations from scheduling operations -- instead of lumping
everything under the generic ``"a2a"`` category.

The mapping is intentionally agent-name-based (not per-skill) because
all skills belonging to the same capability agent share a functional
domain.
"""

import structlog

from app.tools.schema import ToolCategory

logger = structlog.get_logger(__name__)

# Substrings matched (case-insensitive) against agent names and service names.
# Order does not matter -- first match wins, but keys are disjoint today.
_AGENT_CATEGORY_MAP: dict[str, ToolCategory] = {
    "knowledge base": ToolCategory.KNOWLEDGE_BASE,
    "kb-agent": ToolCategory.KNOWLEDGE_BASE,
    "kb_agent": ToolCategory.KNOWLEDGE_BASE,
    "crm": ToolCategory.CRM,
    "appointment": ToolCategory.APPOINTMENT,
    "scheduling": ToolCategory.APPOINTMENT,
}


def resolve_tool_category(agent_name: str) -> ToolCategory:
    """Derive a ToolCategory from an agent's display name or service name.

    Performs case-insensitive substring matching against known agent
    identifiers.  Falls back to ``ToolCategory.SYSTEM`` for unknown
    agents and logs a warning so operators notice the gap.

    Args:
        agent_name: Agent card display name (e.g. ``"Knowledge Base Agent"``)
            or CloudMap service name (e.g. ``"kb-agent"``).

    Returns:
        The matching ``ToolCategory``, or ``ToolCategory.SYSTEM`` if no
        mapping is found.
    """
    normalized = agent_name.lower().strip()
    for key, category in _AGENT_CATEGORY_MAP.items():
        if key in normalized:
            return category

    logger.warning(
        "a2a_category_fallback",
        agent_name=agent_name,
        resolved_category=ToolCategory.SYSTEM.value,
        note="Add mapping to _AGENT_CATEGORY_MAP for meaningful metrics",
    )
    return ToolCategory.SYSTEM
