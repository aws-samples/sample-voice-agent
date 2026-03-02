"""Hangup call tool for the voice agent.

Allows the LLM to programmatically end a call when the conversation
has reached a natural conclusion. The tool queues an EndFrame into
the pipeline, which drains all in-flight audio (including the LLM's
goodbye message) before disconnecting.

Capability requirements:
    - TRANSPORT: Needs an active transport to disconnect from
"""

import structlog
from typing import Any, Dict

from pipecat.frames.frames import EndFrame

from ..capabilities import PipelineCapability
from ..context import ToolContext
from ..result import ToolResult, ToolStatus, error_result
from ..schema import ToolCategory, ToolDefinition, ToolParameter

logger = structlog.get_logger(__name__)


async def hangup_executor(
    arguments: Dict[str, Any],
    context: ToolContext,
) -> ToolResult:
    """Execute the hangup call action.

    Queues an EndFrame into the pipeline to gracefully terminate the call.
    The EndFrame drains after all in-flight frames (including the LLM's
    goodbye TTS audio) have been processed, so the caller hears the full
    farewell before disconnection.

    Args:
        arguments: {"reason": "..."} -- why the call is ending
        context: Tool execution context

    Returns:
        ToolResult with confirmation or error
    """
    reason = arguments.get("reason", "Conversation concluded")

    logger.info(
        "hangup_requested",
        call_id=context.call_id,
        session_id=context.session_id,
        reason=reason,
    )

    if context.queue_frame is None:
        logger.error(
            "hangup_failed_no_queue_frame",
            call_id=context.call_id,
        )
        return error_result(
            error_code="HANGUP_UNAVAILABLE",
            error_message=(
                "Unable to end the call at this time. "
                "The call control mechanism is not available."
            ),
        )

    try:
        await context.queue_frame(EndFrame())

        logger.info(
            "endframe_queued_for_hangup",
            call_id=context.call_id,
            reason=reason,
        )

        return ToolResult(
            status=ToolStatus.SUCCESS,
            content={
                "hangup_initiated": True,
                "reason": reason,
                "call_id": context.call_id,
                "message": (
                    "The call will end after your goodbye message is spoken. "
                    "Say goodbye to the caller now."
                ),
            },
            # Suppress LLM re-inference after hangup. The pipeline is
            # shutting down via EndFrame; a follow-up LLM call would only
            # add latency (~2s) before the actual disconnect and fail with
            # "Unable to send messages before joining" after transport closes.
            run_llm=False,
        )

    except Exception as e:
        logger.error(
            "hangup_failed",
            call_id=context.call_id,
            error=str(e),
            exc_info=True,
        )
        return error_result(
            error_code="HANGUP_FAILED",
            error_message="Unable to end the call. Please try again.",
        )


hangup_tool = ToolDefinition(
    name="hangup_call",
    description=(
        "End the current phone call. Use this ONLY after the conversation has "
        "reached a natural conclusion: the customer's issue is fully resolved, "
        "you have confirmed they don't need further help, and you have said "
        "goodbye. Never hang up while the customer is still speaking or has "
        "unresolved questions."
    ),
    category=ToolCategory.SYSTEM,
    parameters=[
        ToolParameter(
            name="reason",
            type="string",
            description=(
                "Brief description of why the call is ending, e.g. "
                "'Customer issue resolved', 'Customer requested to end call', "
                "'No further questions'."
            ),
            required=True,
        ),
    ],
    executor=hangup_executor,
    timeout_seconds=5.0,
    requires=frozenset({PipelineCapability.TRANSPORT}),
)
