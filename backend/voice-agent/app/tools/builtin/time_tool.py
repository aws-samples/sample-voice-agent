"""Current time tool for the voice agent.

This tool returns the current date and time, useful for answering
time-related questions without external dependencies.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from ..context import ToolContext
from ..result import ToolResult, direct_response_result
from ..schema import ToolCategory, ToolDefinition, ToolParameter
from ..capabilities import PipelineCapability


async def time_executor(
    arguments: Dict[str, Any],
    context: ToolContext,
) -> ToolResult:
    """Get the current date and time.

    Args:
        arguments: {"timezone": "UTC"} (optional)
        context: Tool execution context

    Returns:
        ToolResult with current date/time information
    """
    # Get current time in UTC
    now = datetime.now(timezone.utc)

    # Format for natural language response
    time_str = now.strftime("%I:%M %p")  # e.g., "02:30 PM"
    date_str = now.strftime("%A, %B %d, %Y")  # e.g., "Monday, January 27, 2026"

    return direct_response_result(
        content={
            "current_time": time_str,
            "current_date": date_str,
            "timezone": "UTC",
            "iso_timestamp": now.isoformat(),
            "unix_timestamp": int(now.timestamp()),
        },
        spoken_response=f"It's currently {time_str} UTC on {date_str}. Is there anything else I can help you with?",
    )


time_tool = ToolDefinition(
    name="get_current_time",
    description=(
        "Get the current date and time. Use this when the user asks "
        "what time it is, what today's date is, or needs current time information."
    ),
    category=ToolCategory.SYSTEM,
    parameters=[
        ToolParameter(
            name="timezone",
            type="string",
            description="Timezone name (currently only UTC is supported)",
            required=False,
            enum=["UTC"],
        ),
    ],
    executor=time_executor,
    timeout_seconds=2.0,
    requires_auth=False,
    requires=frozenset({PipelineCapability.BASIC}),
)
