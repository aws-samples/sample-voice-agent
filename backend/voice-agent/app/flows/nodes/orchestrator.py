"""Orchestrator node definition.

The orchestrator is the entry point for every call. It greets the caller,
identifies their intent, and routes them to the appropriate specialist.
It has no domain tools -- only the generic transfer function and global
tools (hangup, time, SIP transfer).

The orchestrator's task message is built dynamically from discovered
A2A agents, so it knows what specialists are available and what they do.

On re-entry (returning from a specialist), the orchestrator asks if there
is anything else the caller needs.
"""

from typing import Dict, List, Optional
from datetime import datetime

import structlog

from pipecat_flows import (
    ContextStrategy,
    ContextStrategyConfig,
    NodeConfig,
)

from ..context import get_summary_prompt
from ..transitions import transfer

logger = structlog.get_logger(__name__)


def _current_datetime_str() -> str:
    """Return a human-readable current date/time string for system prompts."""
    now = datetime.now()
    return now.strftime("%A, %B %-d, %Y at %-I:%M %p")


# System prompt for the orchestrator agent
_ORCHESTRATOR_ROLE = (
    "You are a friendly and professional virtual receptionist for a technology "
    "services company. Your name is Alex. You speak in a warm, conversational "
    "tone appropriate for a phone call. Keep responses concise -- 1-3 sentences. "
    "Never use special characters, URLs, or formatting. "
    "The current date and time is {current_datetime}."
)

# Base task instructions -- {specialist_descriptions} is replaced at runtime
_ORCHESTRATOR_TASK_TEMPLATE = (
    "Your job is to greet callers, understand what they need, and route them "
    "to the right expertise using the transfer function.\n\n"
    "Do NOT attempt to solve technical problems, answer domain-specific questions, "
    "or perform actions yourself. Use the transfer function as soon as you "
    "understand their intent.\n\n"
    "{specialist_descriptions}\n\n"
    "CRITICAL LANGUAGE RULES -- you MUST follow these:\n"
    "- You are ONE seamless assistant named Alex. The caller must never know "
    "that separate systems or specialists exist.\n"
    '- NEVER say: "let me connect you", "let me transfer you", '
    '"I\'ll put you through", "let me bring in", "I\'ll get someone", '
    '"let me route you", "our specialist", "another team", "our department", '
    "or ANY variation that implies a handoff, transfer, connection, or other person.\n"
    '- INSTEAD say things like: "Sure, let me look into that", '
    '"Absolutely, one moment while I pull that up", '
    '"Of course, let me check on that for you".\n'
    "- Then immediately call the transfer function. Do NOT wait for the caller "
    "to confirm after your acknowledgment.\n\n"
    "RETURNING FROM A TOPIC: When you receive a conversation summary, the "
    "caller is already on the line -- this is NOT a new call. Do not re-introduce "
    "yourself. Simply continue naturally, acknowledge what was discussed, and ask "
    "if there is anything else you can help with. If they need help with a "
    "different topic, use the transfer function immediately.\n\n"
    "If the caller says they are done, thank them and end the call using "
    "the hangup_call function."
)

# Fallback when no agents are discovered
_NO_SPECIALISTS_TASK = (
    "Your job is to help callers with their requests. No specialist agents "
    "are currently available, so assist the caller directly using the tools "
    "available to you. If you cannot help, apologize and suggest they call back."
)

# Greeting spoken via TTS when the orchestrator node is activated
_GREETING_TTS = "Hello! Thank you for calling. How can I help you today?"
_RETURN_TTS = "Is there anything else I can help you with?"


def _build_specialist_descriptions(
    agent_descriptions: Optional[Dict[str, str]] = None,
) -> str:
    """Build the specialist descriptions section for the orchestrator task message.

    Args:
        agent_descriptions: Dict mapping node names to agent descriptions.
            e.g., {"kb_agent": "Searches knowledge base...", "crm_agent": "Customer management..."}

    Returns:
        Formatted string listing available specialists for the LLM.
    """
    if not agent_descriptions:
        return ""

    lines = ["Available expertise areas (use the transfer function to switch):"]
    for node_name, description in sorted(agent_descriptions.items()):
        # Truncate very long descriptions for the prompt
        desc = description[:200] + "..." if len(description) > 200 else description
        lines.append(f"- {node_name}: {desc}")

    lines.append(
        "\nUse the transfer function with the area name as the target. "
        "You can also use 'reception' to return here."
    )

    return "\n".join(lines)


def create_orchestrator_node(
    is_return: bool = False,
    agent_descriptions: Optional[Dict[str, str]] = None,
) -> NodeConfig:
    """Create the orchestrator/reception node.

    Args:
        is_return: If True, this is a re-entry from a specialist.
            Uses "anything else?" prompt instead of initial greeting.
        agent_descriptions: Dict mapping node names to agent descriptions,
            used to build the dynamic routing instructions. If None or empty,
            falls back to a no-specialists task message.

    Returns:
        NodeConfig for the orchestrator node.
    """
    pre_actions = []
    if is_return:
        pre_actions.append({"type": "tts_say", "text": _RETURN_TTS})
    else:
        pre_actions.append({"type": "tts_say", "text": _GREETING_TTS})

    # Build task message with dynamic specialist descriptions
    if agent_descriptions:
        specialist_section = _build_specialist_descriptions(agent_descriptions)
        task_content = _ORCHESTRATOR_TASK_TEMPLATE.format(
            specialist_descriptions=specialist_section,
        )
    else:
        task_content = _NO_SPECIALISTS_TASK

    # Build context strategy based on whether this is first entry or return
    context_strategy = None
    if is_return:
        context_strategy = ContextStrategyConfig(
            strategy=ContextStrategy.RESET_WITH_SUMMARY,
            summary_prompt=get_summary_prompt("orchestrator"),
        )

    node = NodeConfig(
        name="orchestrator",
        role_messages=[
            {
                "role": "system",
                "content": _ORCHESTRATOR_ROLE.format(
                    current_datetime=_current_datetime_str()
                ),
            }
        ],
        task_messages=[
            {
                "role": "system",
                "content": task_content,
            }
        ],
        functions=[transfer],
        pre_actions=pre_actions,
        context_strategy=context_strategy,
    )

    logger.debug(
        "orchestrator_node_created",
        is_return=is_return,
        has_context_strategy=context_strategy is not None,
        specialist_count=len(agent_descriptions) if agent_descriptions else 0,
    )

    return node
