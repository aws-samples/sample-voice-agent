"""A2A integration for the voice agent pipeline.

This package provides CloudMap-based discovery of A2A capability agents
and adapters to bridge them into Pipecat's tool calling flow.

Modules:
    discovery: CloudMap service discovery (find agent endpoints)
    registry: AgentRegistry with background polling (manage A2A agents)
    tool_adapter: Pipecat tool handler adapter (route LLM tool calls to A2A agents)
"""

from .discovery import AgentEndpoint, discover_agents
from .registry import (
    AgentEntry,
    AgentRegistry,
    AgentSkillInfo,
)
from .tool_adapter import create_a2a_tool_handler, extract_text_from_result

__all__ = [
    "AgentEndpoint",
    "AgentEntry",
    "AgentRegistry",
    "AgentSkillInfo",
    "create_a2a_tool_handler",
    "discover_agents",
    "extract_text_from_result",
]
