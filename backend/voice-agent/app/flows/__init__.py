"""Multi-agent flow system using Pipecat Flows.

This module implements in-process agent handoff where the LLM context
(system prompt + tools) is swapped mid-call to emulate specialist agents.
The system is a fully connected graph of agent nodes, managed by
Pipecat Flows' FlowManager.

Feature-flagged via SSM parameter `/voice-agent/config/enable-flow-agents`.

Usage:
    from app.flows import create_flow_manager, create_initial_node

    flow_manager = create_flow_manager(task, llm, context_aggregator, ...)
    await flow_manager.initialize(create_initial_node(a2a_registry))
"""

from .flow_config import create_flow_manager, create_initial_node

__all__ = [
    "create_flow_manager",
    "create_initial_node",
]
