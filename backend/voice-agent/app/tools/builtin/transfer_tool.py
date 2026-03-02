"""Transfer to agent tool for the voice agent.

This tool signals that the caller should be transferred to a human agent.
It captures the reason and context for the transfer and executes SIP REFER
via the Daily transport when available.

Capability requirements:
    - TRANSPORT: Needs DailyTransport for sip_refer()
    - SIP_SESSION: Needs a SIP dial-in connection (session ID)
    - TRANSFER_DESTINATION: Needs TRANSFER_DESTINATION env var set

These requirements are declared in the ToolDefinition's `requires` field.
The pipeline's capability detection ensures this tool is only registered
when all three are satisfied -- so the executor can trust they're present
and skip defensive runtime checks for missing configuration.
"""

import structlog
import os
from typing import Any, Dict

from ..capabilities import PipelineCapability
from ..context import ToolContext
from ..result import ToolResult, success_result, error_result
from ..schema import ToolCategory, ToolDefinition, ToolParameter

logger = structlog.get_logger(__name__)


async def transfer_executor(
    arguments: Dict[str, Any],
    context: ToolContext,
) -> ToolResult:
    """Execute transfer to a human agent via SIP REFER.

    This tool initiates a SIP REFER transfer via the Daily transport,
    routing the caller to a human agent while capturing context.

    Because the capability system guarantees TRANSPORT, SIP_SESSION, and
    TRANSFER_DESTINATION are all present before this tool is registered,
    the executor can focus on the transfer logic rather than defensive
    configuration checks.

    Args:
        arguments: {"reason": "...", "department": "...", "priority": "..."}
        context: Tool execution context

    Returns:
        ToolResult with transfer confirmation or error
    """
    reason = arguments.get("reason", "Customer requested transfer")
    department = arguments.get("department", "general")
    priority = arguments.get("priority", "normal")

    # Log the transfer request for audit
    logger.info(
        "transfer_requested",
        call_id=context.call_id,
        department=department,
        priority=priority,
        reason=reason,
    )

    # Read the transfer destination -- guaranteed present by capability detection
    transfer_destination = os.environ.get("TRANSFER_DESTINATION", "")

    # Build context summary from conversation history
    conversation_summary = _build_conversation_summary(context)

    try:
        # Resolve the SIP session ID for the transfer
        sip_session_id = context.sip_session_id
        if not sip_session_id:
            # Fallback: scan transport participants for a SIP participant
            participants = getattr(context.transport, "_participants", {})
            for participant_id, participant in participants.items():
                if participant.get("sipFrom"):
                    sip_session_id = participant_id
                    logger.info("sip_participant_found", sip_session_id=sip_session_id)
                    break

        if not sip_session_id:
            logger.error("sip_session_id_not_found", call_id=context.call_id)
            return error_result(
                error_code="TRANSFER_FAILED",
                error_message="Unable to identify the call to transfer. Please try again.",
            )

        # Execute SIP REFER via Daily transport
        logger.info(
            "sip_refer_executing",
            call_id=context.call_id,
            destination=transfer_destination,
            sip_session_id=sip_session_id,
        )

        # Daily expects: { sessionId: <participant_id>, toEndPoint: <sip_uri> }
        # Note: toEndPoint has a capital 'P' - this is required by Daily's API
        await context.transport.sip_refer(
            {
                "sessionId": sip_session_id,
                "toEndPoint": transfer_destination,
            }
        )

        logger.info(
            "sip_refer_success",
            call_id=context.call_id,
            destination=transfer_destination,
            sip_session_id=sip_session_id,
        )

        return success_result(
            {
                "transfer_initiated": True,
                "department": department,
                "priority": priority,
                "reason": reason,
                "call_id": context.call_id,
                "destination": transfer_destination,
                "conversation_summary": conversation_summary,
                "message": (
                    f"I'm transferring you to our {department} team. "
                    "Please hold while I connect you with an agent."
                ),
            }
        )

    except Exception as e:
        logger.error(
            "sip_refer_failed",
            call_id=context.call_id,
            destination=transfer_destination,
            error=str(e),
            exc_info=True,
        )
        return error_result(
            error_code="TRANSFER_FAILED",
            error_message=(
                "I'm unable to complete the transfer at this moment. "
                "Let me try to assist you further or please call back later."
            ),
        )


def _build_conversation_summary(context: ToolContext) -> str:
    """Build a brief summary of the conversation for the human agent.

    Args:
        context: Tool context with conversation history

    Returns:
        Brief summary string
    """
    if not context.conversation_history:
        return "No conversation history available."

    # Get last few exchanges
    recent = context.conversation_history[-6:]  # Last 3 exchanges

    summary_parts = []
    for msg in recent:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        # Truncate long messages
        if len(content) > 100:
            content = content[:100] + "..."
        summary_parts.append(f"{role.title()}: {content}")

    return " | ".join(summary_parts)


transfer_tool = ToolDefinition(
    name="transfer_to_agent",
    description=(
        "Transfer the caller to a human agent. Use this when the caller "
        "explicitly requests to speak with a person, when you cannot help "
        "with their request, or when the issue requires human intervention."
    ),
    category=ToolCategory.SYSTEM,
    parameters=[
        ToolParameter(
            name="reason",
            type="string",
            description=(
                "Brief description of why the transfer is needed. "
                "Include relevant context for the human agent."
            ),
            required=True,
        ),
        ToolParameter(
            name="department",
            type="string",
            description="Department to transfer to",
            required=False,
            enum=["general", "billing", "technical", "sales", "complaints"],
        ),
        ToolParameter(
            name="priority",
            type="string",
            description="Priority level for the transfer",
            required=False,
            enum=["low", "normal", "high", "urgent"],
        ),
    ],
    executor=transfer_executor,
    timeout_seconds=30.0,  # SIP REFER can take time to negotiate
    requires_auth=False,
    requires=frozenset(
        {
            PipelineCapability.TRANSPORT,
            PipelineCapability.SIP_SESSION,
            PipelineCapability.TRANSFER_DESTINATION,
        }
    ),
)
