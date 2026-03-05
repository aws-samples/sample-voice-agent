"""Summary prompt templates and context helpers for agent transitions.

Supports both generic and domain-aware summary prompts. When transitioning
to a specialist node with Agent Card metadata, the summary prompt is
tailored to extract context relevant to that domain. When no metadata is
available, falls back to a generic summary.
"""

from typing import Optional

# Generic summary prompt used with ContextStrategy.RESET_WITH_SUMMARY
# when transitioning between nodes. Designed to work for any specialist type.
GENERIC_SUMMARY_PROMPT = (
    "Output ONLY a factual bullet-point summary of the conversation so far. "
    "Do NOT generate dialogue, questions, or new conversational turns.\n\n"
    "Include:\n"
    "- The caller's issue or request\n"
    "- Key details or information gathered\n"
    "- Actions taken or attempted and their results\n"
    "- ALL identifiers: customer IDs, names, phone numbers, ticket numbers, "
    "appointment IDs -- in the exact format returned by tools\n\n"
    "Format: bullet points only. 3-5 bullets maximum."
)

# Orchestrator-specific summary prompt for returning to reception.
# Slightly different focus: what was accomplished, what's outstanding.
ORCHESTRATOR_SUMMARY_PROMPT = (
    "Output ONLY a factual bullet-point summary. "
    "Do NOT generate dialogue, questions, or new conversational turns.\n\n"
    "Include:\n"
    "- What the caller needed help with\n"
    "- What was accomplished (with specific results, IDs, confirmation numbers)\n"
    "- Any outstanding items or next steps\n\n"
    "Format: bullet points only. 3-5 bullets maximum."
)

# Template for domain-aware specialist summary prompts.
# {agent_description} is replaced with the Agent Card description.
_DOMAIN_SUMMARY_TEMPLATE = (
    "The conversation is shifting focus to: {agent_description}\n\n"
    "Output ONLY a factual bullet-point summary of the conversation so far. "
    "Do NOT generate dialogue, questions, or new conversational turns.\n\n"
    "You MUST include:\n"
    "- The caller's original request and what they still need\n"
    "- ALL identifiers discovered during the conversation: customer_id, "
    "customer names, phone numbers, account numbers, appointment IDs, "
    "ticket numbers -- in the exact format returned by tools "
    "(e.g., 'Customer ID: cust-002', 'Ticket: TICKET-2026-ABC')\n"
    "- Key actions already taken and their results\n"
    "- Specific details mentioned: dates, times, addresses, product names, "
    "error descriptions\n\n"
    "Format: bullet points only. 3-5 bullets maximum. NEVER omit identifiers."
)


def get_summary_prompt(
    node_name: str = "",
    agent_description: Optional[str] = None,
) -> str:
    """Get the summary prompt for a given node.

    When ``agent_description`` is provided, returns a domain-aware prompt
    that instructs the LLM to extract context relevant to the specialist's
    area of expertise. Otherwise falls back to the generic prompt.

    Args:
        node_name: The target node name. If "orchestrator" or "reception",
            returns the orchestrator-specific prompt.
        agent_description: Optional Agent Card description for the target
            specialist. When provided, generates a domain-aware prompt.

    Returns:
        Summary prompt string.
    """
    if node_name in ("orchestrator", "reception"):
        return ORCHESTRATOR_SUMMARY_PROMPT

    if agent_description:
        return _DOMAIN_SUMMARY_TEMPLATE.format(agent_description=agent_description)

    return GENERIC_SUMMARY_PROMPT
