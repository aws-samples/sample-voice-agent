"""Dependency gating for multi-agent transfers.

Agents declare capabilities via skill-level tags on their A2A Agent Card:
    - ``provides:<key>`` -- this agent's skill satisfies the named dependency
    - ``requires:<key>`` -- this agent needs the dependency before transfer

At transfer time, the flow system checks whether the target agent's
requirements are satisfied by context already gathered during the call.
If not, the transfer is redirected to an agent that *provides* the missing
dependency, with the original target queued as the intent.

Example tag usage (on Agent Card skills):
    CRM lookup_customer:  tags=["provides:customer_id"]
    Appointment book:     tags=["requires:customer_id"]

When KB tries to transfer to appointment and customer_id hasn't been
provided yet, the transfer is redirected to CRM with a reason that
includes the original intent (scheduling an appointment).

All state is stored in ``flow_manager.state`` under well-known keys
so it survives across node transitions.
"""

from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

logger = structlog.get_logger(__name__)

# Keys in flow_manager.state
SATISFIED_DEPS_KEY = "_satisfied_dependencies"
PENDING_TARGET_KEY = "_pending_transfer_target"
PENDING_REASON_KEY = "_pending_transfer_reason"

# Tag prefixes
_PROVIDES_PREFIX = "provides:"
_REQUIRES_PREFIX = "requires:"


def parse_skill_tags(tags: List[str]) -> Tuple[Set[str], Set[str]]:
    """Extract provides and requires keys from skill tags.

    Args:
        tags: List of tag strings (e.g., ["provides:customer_id", "crm"])

    Returns:
        Tuple of (provides_set, requires_set)
    """
    provides: Set[str] = set()
    requires: Set[str] = set()

    for tag in tags:
        tag = tag.strip().lower()
        if tag.startswith(_PROVIDES_PREFIX):
            key = tag[len(_PROVIDES_PREFIX) :]
            if key:
                provides.add(key)
        elif tag.startswith(_REQUIRES_PREFIX):
            key = tag[len(_REQUIRES_PREFIX) :]
            if key:
                requires.add(key)

    return provides, requires


def aggregate_agent_tags(
    skills_tags: List[List[str]],
) -> Tuple[Set[str], Set[str]]:
    """Aggregate provides/requires across all skills of an agent.

    An agent *provides* a key if ANY of its skills provides it.
    An agent *requires* a key if ANY of its skills requires it.

    Args:
        skills_tags: List of tag lists, one per skill

    Returns:
        Tuple of (agent_provides, agent_requires)
    """
    provides: Set[str] = set()
    requires: Set[str] = set()

    for tags in skills_tags:
        p, r = parse_skill_tags(tags)
        provides.update(p)
        requires.update(r)

    return provides, requires


def mark_dependency_satisfied(state: Dict[str, Any], key: str) -> None:
    """Record that a dependency has been satisfied during this call.

    Args:
        state: flow_manager.state dict
        key: The dependency key (e.g., "customer_id")
    """
    satisfied = state.get(SATISFIED_DEPS_KEY, set())
    satisfied.add(key)
    state[SATISFIED_DEPS_KEY] = satisfied

    logger.info("dependency_satisfied", key=key, all_satisfied=sorted(satisfied))


def get_satisfied_dependencies(state: Dict[str, Any]) -> Set[str]:
    """Get the set of dependencies satisfied so far in this call.

    Args:
        state: flow_manager.state dict

    Returns:
        Set of satisfied dependency keys
    """
    return state.get(SATISFIED_DEPS_KEY, set())


def check_transfer_requirements(
    target_name: str,
    target_requires: Set[str],
    satisfied: Set[str],
    provider_map: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    """Check if a transfer target's requirements are met.

    If requirements are unmet, finds a provider agent to redirect to.

    Args:
        target_name: The intended transfer target node name
        target_requires: Set of dependency keys the target needs
        satisfied: Set of already-satisfied dependency keys
        provider_map: Maps dependency key -> node_name that provides it

    Returns:
        None if requirements are met (transfer can proceed).
        Dict with redirect info if requirements are unmet:
            {
                "redirect_to": str,  -- the provider agent to go to first
                "missing": list,     -- unsatisfied dependency keys
                "original_target": str,
                "provider_description": str,
            }
    """
    if not target_requires:
        return None

    missing = target_requires - satisfied
    if not missing:
        return None

    # Find a provider for the first missing dependency
    for dep_key in sorted(missing):
        provider = provider_map.get(dep_key)
        if provider:
            logger.info(
                "dependency_gate_redirect",
                target=target_name,
                missing_dep=dep_key,
                redirect_to=provider,
                all_missing=sorted(missing),
            )
            return {
                "redirect_to": provider,
                "missing": sorted(missing),
                "original_target": target_name,
            }

    # No provider found for missing deps -- log warning, allow transfer anyway
    # (the self-gating prompt on the target agent is the fallback)
    logger.warning(
        "dependency_gate_no_provider",
        target=target_name,
        missing=sorted(missing),
    )
    return None


def set_pending_target(
    state: Dict[str, Any],
    target: str,
    reason: str,
) -> None:
    """Store a pending transfer target for after dependencies are satisfied.

    Args:
        state: flow_manager.state dict
        target: The original intended target
        reason: The original transfer reason
    """
    state[PENDING_TARGET_KEY] = target
    state[PENDING_REASON_KEY] = reason


def pop_pending_target(state: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Pop the pending transfer target if one exists.

    Args:
        state: flow_manager.state dict

    Returns:
        (target, reason) tuple if pending, else None
    """
    target = state.pop(PENDING_TARGET_KEY, None)
    reason = state.pop(PENDING_REASON_KEY, None)
    if target:
        return target, reason or ""
    return None
