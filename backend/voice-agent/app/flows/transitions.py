"""Generic transfer function and transition utilities for Pipecat Flows.

The transfer function is a Pipecat Flows "direct function" -- its schema
is auto-extracted from the type hints and docstring. It handles all
agent-to-agent transitions in the fully connected graph.

Loop protection: tracks transition count per FlowManager instance
(via flow_manager.state) and forces return to orchestrator after a
configurable threshold.

Dependency gating: checks whether the target agent's requirements
(from ``requires:<key>`` skill tags) are satisfied before allowing
the transfer. If not, redirects to the provider agent that can
satisfy the missing dependency.
"""

import time
from typing import Any, Callable, Dict, Optional

import structlog

from .dependencies import (
    check_transfer_requirements,
    get_satisfied_dependencies,
    set_pending_target,
)

logger = structlog.get_logger(__name__)

# Default maximum transitions per call before loop protection activates
DEFAULT_MAX_TRANSITIONS = 10

# Key used in flow_manager.state to track transition count
_TRANSITION_COUNT_KEY = "transition_count"
_TRANSITION_HISTORY_KEY = "transition_history"

# Key used to store MetricsCollector in flow_manager.state
_COLLECTOR_KEY = "_collector"

# Registry of node factory functions, populated by register_node_factory()
_node_factories: Dict[str, Callable] = {}


def register_node_factory(target_name: str, factory: Callable) -> None:
    """Register a node factory function for a target name.

    Args:
        target_name: The target identifier (e.g., "computer_support")
        factory: Callable that returns a NodeConfig
    """
    _node_factories[target_name] = factory
    logger.debug("node_factory_registered", target=target_name)


def get_available_targets() -> list[str]:
    """Get the list of registered target names.

    Returns:
        Sorted list of available target names.
    """
    return sorted(_node_factories.keys())


def clear_node_factories() -> None:
    """Clear all registered node factories. Used in testing."""
    _node_factories.clear()


def _get_max_transitions() -> int:
    """Get the maximum transitions per call from config.

    Falls back to DEFAULT_MAX_TRANSITIONS if config is unavailable.
    """
    try:
        from app.services import get_config_service

        svc = get_config_service()
        if svc.is_configured():
            return svc.config.flow_max_transitions
    except Exception:
        pass
    return DEFAULT_MAX_TRANSITIONS


async def transfer(flow_manager: Any, target: str, reason: str) -> tuple:
    """Switch your focus to a different expertise area to help the caller.

    Use this function when the caller's request requires a different set of
    tools or knowledge. The available areas are listed in your system
    instructions. Use 'reception' to return to general assistance.

    IMPORTANT: Do NOT announce this action to the caller. Do NOT say you are
    transferring, connecting, or routing them. Simply use the function silently
    and continue the conversation naturally.

    Args:
        target: The expertise area to switch to, or 'reception' for general
            assistance.
        reason: Internal note about why the switch is needed and key context
            to carry forward. The caller does not see this.
    """
    # NOTE: cancel_on_interruption=False is set via the attribute below
    # the function definition. A transfer should never be cancelled mid-flight.
    from pipecat_flows import FlowResult, NodeConfig

    transfer_start = time.monotonic()
    from_node = flow_manager.current_node

    # Retrieve MetricsCollector from flow_manager.state (set by create_flow_manager)
    collector = flow_manager.state.get(_COLLECTOR_KEY)

    # Track transition count for loop protection
    count = flow_manager.state.get(_TRANSITION_COUNT_KEY, 0) + 1
    flow_manager.state[_TRANSITION_COUNT_KEY] = count

    # Track transition history for debugging
    history = flow_manager.state.get(_TRANSITION_HISTORY_KEY, [])
    history.append({"from": from_node, "to": target, "reason": reason})
    flow_manager.state[_TRANSITION_HISTORY_KEY] = history

    logger.info(
        "agent_transfer_requested",
        from_node=from_node,
        target=target,
        reason=reason,
        transition_count=count,
    )

    # Loop protection: force return to orchestrator after too many transitions
    max_transitions = _get_max_transitions()
    if count > max_transitions:
        logger.warning(
            "agent_transfer_loop_detected",
            transition_count=count,
            max_transitions=max_transitions,
            target=target,
            history=history[-5:],  # Last 5 transitions for debugging
        )

        actual_target = "orchestrator"
        # Force return to orchestrator with a warning
        if "orchestrator" in _node_factories:
            node = _node_factories["orchestrator"]()
        elif "reception" in _node_factories:
            node = _node_factories["reception"]()
            actual_target = "reception"
        else:
            # Last resort: return error result, stay in current node
            result: FlowResult = {
                "error": True,
                "message": "Too many transfers. Please help the caller directly.",
            }
            # Record loop protection activation even on fallback
            if collector:
                try:
                    elapsed_ms = (time.monotonic() - transfer_start) * 1000
                    collector.record_agent_transition(
                        from_node=from_node or "unknown",
                        to_node=target,
                        reason=reason,
                        transition_latency_ms=elapsed_ms,
                        loop_protection=True,
                    )
                except Exception:
                    pass
            return result, None

        # Record loop-protection transition
        elapsed_ms = (time.monotonic() - transfer_start) * 1000
        if collector:
            try:
                collector.set_agent_node(actual_target)
                collector.record_agent_transition(
                    from_node=from_node or "unknown",
                    to_node=actual_target,
                    reason="Loop protection activated -- too many agent transitions",
                    transition_latency_ms=elapsed_ms,
                    loop_protection=True,
                )
            except Exception:
                pass

        result = {
            "transferred_to": "reception",
            "reason": "Loop protection activated -- too many agent transitions",
            "original_target": target,
        }
        return result, node

    # Check for self-transfer
    if target == from_node:
        logger.info(
            "agent_transfer_self_transfer",
            node=target,
            reason=reason,
        )
        result = {
            "error": False,
            "message": (
                f"You are already the {target} specialist. "
                "Continue helping the caller with their current issue."
            ),
            "stayed_in": target,
        }
        return result, None

    # Look up the target node factory
    if target not in _node_factories:
        available = get_available_targets()
        logger.warning(
            "agent_transfer_unknown_target",
            target=target,
            available=available,
        )
        result = {
            "error": True,
            "message": (
                f"Unknown specialist '{target}'. "
                f"Available specialists: {', '.join(available)}"
            ),
        }
        return result, None

    # Dependency gating: check if target's requirements are satisfied
    requirements_map = flow_manager.state.get("_requirements_map", {})
    target_requires = requirements_map.get(target, set())
    if target_requires:
        satisfied = get_satisfied_dependencies(flow_manager.state)
        provider_map = flow_manager.state.get("_provider_map", {})
        redirect = check_transfer_requirements(
            target_name=target,
            target_requires=target_requires,
            satisfied=satisfied,
            provider_map=provider_map,
        )
        if redirect:
            # Store the original target so the provider agent's prompt
            # mentions the caller's end goal
            set_pending_target(flow_manager.state, target, reason)

            redirect_to = redirect["redirect_to"]
            missing = redirect["missing"]

            # Build a reason that tells the provider agent what to do
            redirect_reason = (
                f"The caller needs {target} but must be identified first "
                f"(missing: {', '.join(missing)}). "
                f"Original request: {reason}"
            )

            logger.info(
                "agent_transfer_dependency_redirect",
                original_target=target,
                redirect_to=redirect_to,
                missing_deps=missing,
                reason=reason,
            )

            # Redirect to the provider agent instead
            if redirect_to not in _node_factories:
                logger.error(
                    "dependency_redirect_target_missing",
                    redirect_to=redirect_to,
                )
                # Fall through to original target -- self-gating is the backup
            else:
                target = redirect_to
                reason = redirect_reason

    # Create the target node
    node_factory = _node_factories[target]
    node = node_factory()
    elapsed_ms = (time.monotonic() - transfer_start) * 1000

    result = {
        "transferred_to": target,
        "reason": reason,
        "transition_number": count,
    }

    logger.info(
        "agent_transfer_executing",
        from_node=from_node,
        to_node=target,
        transition_number=count,
    )

    # Update agent node dimension and record transition metrics
    if collector:
        try:
            collector.set_agent_node(target)
            collector.record_agent_transition(
                from_node=from_node or "unknown",
                to_node=target,
                reason=reason,
                transition_latency_ms=elapsed_ms,
            )
        except Exception:
            pass

    return result, node


# Protect transfer from barge-in cancellation. Without this attribute,
# FlowsDirectFunctionWrapper defaults cancel_on_interruption=True and a
# user interruption during the transition would abort the in-flight transfer.
transfer._flows_cancel_on_interruption = False
