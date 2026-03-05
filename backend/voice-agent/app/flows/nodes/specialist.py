"""Generic specialist node definition.

Creates a specialist agent node dynamically from an A2A AgentEntry.
The node's persona, tools, and transition phrase are all derived from
the Agent Card metadata -- no hard-coded specialist definitions needed.

Deploying a new A2A capability agent and registering it in CloudMap
automatically creates a new specialist node with zero voice-agent
code changes.
"""

from typing import Any, List, Optional
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


# Template for the specialist role message.
# {agent_description} is replaced with the Agent Card description.
# {current_datetime} is replaced with the current date/time.
_SPECIALIST_ROLE_TEMPLATE = (
    "You are Alex, a friendly and professional virtual assistant for a "
    "technology services company. {agent_description} "
    "You are continuing an ongoing phone conversation with the caller. "
    "Maintain the same warm, conversational tone throughout. "
    "Keep responses concise -- 1-3 sentences per turn. "
    "Never use special characters, URLs, or formatting. "
    "The current date and time is {current_datetime}."
)

# Template for the specialist task message.
# {available_targets} is optionally replaced with peer specialist info.
_SPECIALIST_TASK_TEMPLATE = (
    "Help the caller with their request using your available tools. "
    "Ask clarifying questions when needed before taking action. "
    "Continue the conversation naturally -- do NOT re-introduce yourself, "
    "do NOT repeat information the caller already shared, and do NOT "
    "mention any transition or handoff. Simply confirm what you're going "
    "to help with and get started.\n\n"
    "If the caller's issue is resolved, ask if they need help with anything "
    "else. If they have a different type of question outside your current "
    "tools, use the transfer function to switch focus.\n\n"
    "CRITICAL LANGUAGE RULES -- you MUST follow these:\n"
    "- You are ONE seamless assistant named Alex. The caller must never know "
    "that separate systems or specialists exist.\n"
    '- NEVER say: "let me connect you", "let me transfer you", '
    '"I\'ll put you through", "let me bring in", "I\'ll get someone", '
    '"let me get you connected", "let me route you", "our specialist", '
    '"another team", "our department", "someone who", "the right person", '
    "or ANY variation that implies a handoff, transfer, connection, or other person.\n"
    '- INSTEAD say things like: "Sure, let me look into that", '
    '"Absolutely, one moment while I pull that up", '
    '"Of course, let me check on that for you".\n'
    "- Then immediately call the transfer function. Do NOT wait for the caller "
    "to confirm after your acknowledgment.\n\n"
    "{available_targets}"
)

# Template for the transition TTS phrase — kept brief to avoid
# redundancy with the LLM's opening message in the new node.
_TRANSITION_TTS_TEMPLATE = "One moment please."


def slugify_service_name(name: str) -> str:
    """Convert a CloudMap service name to a node name.

    Replaces hyphens with underscores and lowercases.
    e.g., 'crm-agent' -> 'crm_agent', 'knowledge-base-agent' -> 'knowledge_base_agent'

    Args:
        name: CloudMap service name

    Returns:
        Slugified node name suitable for use as a transfer target.
    """
    return name.lower().replace("-", "_")


def create_specialist_node(
    node_name: str,
    agent_name: str,
    agent_description: str,
    a2a_functions: Optional[List[Any]] = None,
    peer_descriptions: Optional[dict[str, str]] = None,
    agent_requires: Optional[set[str]] = None,
) -> NodeConfig:
    """Create a specialist node dynamically from Agent Card metadata.

    This is the generic specialist node factory. Every A2A capability
    agent gets one of these nodes, with persona and tools derived from
    its Agent Card.

    Args:
        node_name: The node name (slugified CloudMap service name)
        agent_name: The human-readable agent name from the Agent Card
        agent_description: The agent's description from the Agent Card
        a2a_functions: List of Pipecat Flows-compatible A2A tool functions
            for this agent's skills
        peer_descriptions: Dict mapping other specialist node names to their
            descriptions, so this specialist can transfer directly to peers.
        agent_requires: Set of dependency keys this agent needs (from
            ``requires:<key>`` skill tags). Used to add self-gating
            instructions to the task prompt.

    Returns:
        NodeConfig for the specialist node.
    """
    # Build persona from agent description
    role_content = _SPECIALIST_ROLE_TEMPLATE.format(
        agent_description=agent_description,
        current_datetime=_current_datetime_str(),
    )

    # Build available transfer targets section
    targets_section = ""
    if peer_descriptions:
        peers = {k: v for k, v in peer_descriptions.items() if k != node_name}
        if peers:
            lines = [
                "You can switch to these other expertise areas using the transfer function:"
            ]
            for peer_name, peer_desc in sorted(peers.items()):
                desc = peer_desc[:150] + "..." if len(peer_desc) > 150 else peer_desc
                lines.append(f"- {peer_name}: {desc}")
            lines.append("- reception: Return to general assistance")
            lines.append(
                "\nSwitch directly to the most appropriate area "
                "rather than going back to reception when possible."
            )
            targets_section = "\n".join(lines)

    # Build task content
    task_content = _SPECIALIST_TASK_TEMPLATE.format(
        available_targets=targets_section,
    )

    # Self-gating: if this agent has requirements, add instructions
    # to verify them before performing actions. The wording is softened
    # to check the conversation summary -- if the caller was routed here
    # via the dependency system, the summary will already contain the
    # required context (e.g., customer_id from CRM lookup).
    if agent_requires:
        req_descriptions = {
            "customer_id": (
                "A customer_id is needed to book, cancel, or reschedule "
                "appointments. Check the conversation summary -- if it "
                "mentions a customer ID or customer name from a previous "
                "lookup, you already have it and can proceed. Only transfer "
                "to the CRM specialist if no customer information is present "
                "in the conversation context at all."
            ),
        }
        gate_lines = ["\nPREREQUISITES (check conversation context first):"]
        for req in sorted(agent_requires):
            desc = req_descriptions.get(
                req,
                f"The '{req}' dependency is needed. Check if it was already "
                "provided in the conversation summary before transferring "
                "the caller elsewhere.",
            )
            gate_lines.append(f"- {req}: {desc}")
        task_content += "\n".join(gate_lines)

    # Build transition phrase
    transition_tts = _TRANSITION_TTS_TEMPLATE

    # Node functions: transfer + any A2A tools for this agent
    functions: List[Any] = [transfer]
    if a2a_functions:
        functions.extend(a2a_functions)

    node = NodeConfig(
        name=node_name,
        role_messages=[
            {
                "role": "system",
                "content": role_content,
            }
        ],
        task_messages=[
            {
                "role": "system",
                "content": task_content,
            }
        ],
        functions=functions,
        pre_actions=[
            {"type": "tts_say", "text": transition_tts},
        ],
        context_strategy=ContextStrategyConfig(
            strategy=ContextStrategy.RESET_WITH_SUMMARY,
            summary_prompt=get_summary_prompt(
                node_name=node_name,
                agent_description=agent_description,
            ),
        ),
    )

    logger.debug(
        "specialist_node_created",
        node_name=node_name,
        agent_name=agent_name,
        a2a_function_count=len(a2a_functions) if a2a_functions else 0,
        total_functions=len(functions),
        requires=sorted(agent_requires) if agent_requires else [],
    )

    return node
