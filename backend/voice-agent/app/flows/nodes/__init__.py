"""Agent node definitions for the multi-agent flow system.

Each node represents an agent persona with:
- role_messages: The agent's identity and behavior
- task_messages: Specific instructions for the current task
- functions: Tools available to this agent (transition + domain tools)
- context_strategy: How conversation history is handled on entry
- pre_actions: TTS phrases spoken during transition

Specialist nodes are created dynamically from A2A Agent Card data.
The orchestrator is the only static node definition.
"""

from .orchestrator import create_orchestrator_node
from .specialist import create_specialist_node, slugify_service_name

__all__ = [
    "create_orchestrator_node",
    "create_specialist_node",
    "slugify_service_name",
]
