"""Agent Registry with background polling for A2A capability agents.

Maintains a live routing table of discovered A2A agents and their skills.
Polls CloudMap periodically to discover new agents and remove stale ones.
Caches A2AAgent instances across polling cycles.

Usage:
    registry = AgentRegistry(namespace="voice-agent-capabilities")
    await registry.start_polling(interval_seconds=30)

    # Get Bedrock tool specs for all discovered capabilities
    tool_specs = registry.get_tool_definitions()

    # Route a skill to its A2AAgent
    entry = registry.get_agent_for_skill("search_knowledge_base")
    result = await entry.agent.invoke_async("What is the return policy?")

    await registry.stop_polling()
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

from .discovery import AgentEndpoint, discover_agents

logger = structlog.get_logger(__name__)

# Lazy import to avoid hard dependency at module level.
# A2AAgent is only needed when actually connecting to remote agents.
# The a2a extra must be installed: pip install 'strands-agents[a2a]'
_A2AAgent = None


def _get_a2a_agent_class():
    """Lazily import A2AAgent to avoid import errors when strands-agents[a2a] isn't installed."""
    global _A2AAgent
    if _A2AAgent is None:
        from strands.agent.a2a_agent import A2AAgent

        _A2AAgent = A2AAgent
    return _A2AAgent


@dataclass
class AgentSkillInfo:
    """Metadata about a single skill from an A2A agent's Agent Card.

    Attributes:
        skill_id: Unique skill identifier (e.g., "search_knowledge_base")
        skill_name: Display name of the skill
        description: Full description (from @tool docstring)
        agent_name: Name of the agent providing this skill
        agent_url: URL of the agent endpoint
        tags: Optional tags from the Agent Card
    """

    skill_id: str
    skill_name: str
    description: str
    agent_name: str
    agent_url: str
    tags: List[str] = field(default_factory=list)


@dataclass
class AgentEntry:
    """A cached A2A agent with its metadata.

    Attributes:
        agent: The A2AAgent client instance (cached)
        endpoint: The CloudMap endpoint info
        agent_name: Name from the Agent Card
        agent_description: Description from the Agent Card
        skills: List of skill metadata from the Agent Card
    """

    agent: Any  # A2AAgent instance
    endpoint: AgentEndpoint
    agent_name: str
    agent_description: str
    skills: List[AgentSkillInfo] = field(default_factory=list)


class AgentRegistry:
    """Registry of A2A capability agents discovered via CloudMap.

    Polls CloudMap periodically to discover agents, fetches their Agent Cards,
    and builds a routing table mapping skill IDs to A2AAgent instances.

    The routing table is swapped atomically (dict reference replacement) so
    readers never see a partially-built table.
    """

    # Number of consecutive empty CloudMap responses before clearing the routing table
    EMPTY_POLL_GRACE_COUNT = 3

    def __init__(
        self,
        namespace: str,
        region: Optional[str] = None,
        a2a_timeout: int = 30,
    ):
        """Initialize the registry.

        Args:
            namespace: CloudMap HTTP namespace name
            region: AWS region (defaults to AWS_REGION env var)
            a2a_timeout: Timeout in seconds for A2A operations (card fetch, invoke)
        """
        self.namespace = namespace
        self.region = region
        self.a2a_timeout = a2a_timeout

        # Routing tables (atomically swapped)
        self._skill_table: Dict[str, AgentEntry] = {}  # skill_id -> AgentEntry
        self._agent_cache: Dict[str, AgentEntry] = {}  # agent_url -> AgentEntry

        # Polling state
        self._poll_task: Optional[asyncio.Task] = None
        self._running = False

        # Grace period tracking for transient empty discovery results
        self._consecutive_empty_polls = 0

    async def start_polling(self, interval_seconds: int = 30) -> None:
        """Start background polling for agent discovery.

        Args:
            interval_seconds: Seconds between CloudMap polls
        """
        if self._running:
            logger.warning("agent_registry_already_polling")
            return

        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop(interval_seconds))
        logger.info(
            "agent_registry_polling_started",
            namespace=self.namespace,
            interval_seconds=interval_seconds,
        )

    async def stop_polling(self) -> None:
        """Stop background polling gracefully."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        logger.info("agent_registry_polling_stopped")

    async def refresh(self) -> None:
        """Perform one discovery + card fetch cycle.

        Discovers agents via CloudMap, fetches Agent Cards for any new
        endpoints, and atomically swaps the routing table.
        """
        refresh_start = time.monotonic()
        A2AAgent = _get_a2a_agent_class()

        # Discover endpoints from CloudMap
        discover_start = time.monotonic()
        endpoints = await discover_agents(
            namespace=self.namespace,
            region=self.region,
        )
        discover_ms = (time.monotonic() - discover_start) * 1000

        if not endpoints:
            if self._skill_table:
                self._consecutive_empty_polls += 1
                if self._consecutive_empty_polls < self.EMPTY_POLL_GRACE_COUNT:
                    logger.warning(
                        "agent_registry_empty_discovery_grace",
                        previous_agent_count=len(self._agent_cache),
                        consecutive_empty_polls=self._consecutive_empty_polls,
                        grace_remaining=self.EMPTY_POLL_GRACE_COUNT
                        - self._consecutive_empty_polls,
                    )
                    return  # Keep existing routing table
                else:
                    logger.error(
                        "agent_registry_all_agents_gone_confirmed",
                        previous_count=len(self._agent_cache),
                        consecutive_empty_polls=self._consecutive_empty_polls,
                    )
            # Swap to empty (either no previous table, or grace period exhausted)
            self._skill_table = {}
            self._agent_cache = {}
            return

        # Non-empty discovery — reset grace counter
        self._consecutive_empty_polls = 0

        new_agent_cache: Dict[str, AgentEntry] = {}
        new_skill_table: Dict[str, AgentEntry] = {}

        for ep in endpoints:
            try:
                # Reuse cached agent if endpoint hasn't changed
                if ep.url in self._agent_cache:
                    entry = self._agent_cache[ep.url]
                    new_agent_cache[ep.url] = entry
                    for skill in entry.skills:
                        new_skill_table[skill.skill_id] = entry
                    continue

                # New agent — create A2AAgent and fetch card
                card_start = time.monotonic()
                agent = A2AAgent(
                    endpoint=ep.url,
                    timeout=self.a2a_timeout,
                )
                card = await agent.get_agent_card()

                skills = []
                for skill in card.skills or []:
                    skill_info = AgentSkillInfo(
                        skill_id=skill.id,
                        skill_name=skill.name,
                        description=skill.description or "",
                        agent_name=card.name or ep.name,
                        agent_url=ep.url,
                        tags=list(skill.tags) if skill.tags else [],
                    )
                    skills.append(skill_info)

                entry = AgentEntry(
                    agent=agent,
                    endpoint=ep,
                    agent_name=card.name or ep.name,
                    agent_description=card.description or "",
                    skills=skills,
                )

                new_agent_cache[ep.url] = entry
                for skill_info in skills:
                    if skill_info.skill_id in new_skill_table:
                        logger.warning(
                            "agent_registry_duplicate_skill",
                            skill_id=skill_info.skill_id,
                            agent_a=new_skill_table[skill_info.skill_id].agent_name,
                            agent_b=entry.agent_name,
                        )
                    new_skill_table[skill_info.skill_id] = entry

                logger.info(
                    "agent_registry_agent_discovered",
                    agent_name=entry.agent_name,
                    url=ep.url,
                    skills=[s.skill_id for s in skills],
                    card_fetch_ms=round((time.monotonic() - card_start) * 1000),
                )

            except Exception as e:
                # Carry forward cached entry if this agent was previously known
                # (keyed by service name to survive IP rotation)
                carried = False
                for cached_url, cached_entry in self._agent_cache.items():
                    if cached_entry.endpoint.name == ep.name:
                        new_agent_cache[cached_url] = cached_entry
                        for skill in cached_entry.skills:
                            new_skill_table[skill.skill_id] = cached_entry
                        carried = True
                        break

                logger.warning(
                    "agent_registry_card_fetch_failed",
                    agent=ep.name,
                    url=ep.url,
                    error=str(e),
                    error_type=type(e).__name__,
                    carried_forward=carried,
                )
                continue

        # Log changes
        old_skills = set(self._skill_table.keys())
        new_skills = set(new_skill_table.keys())
        added = new_skills - old_skills
        removed = old_skills - new_skills
        if added:
            logger.info("agent_registry_skills_added", skills=list(added))
        if removed:
            logger.info("agent_registry_skills_removed", skills=list(removed))

        # Atomic swap
        self._agent_cache = new_agent_cache
        self._skill_table = new_skill_table

        refresh_ms = (time.monotonic() - refresh_start) * 1000
        logger.info(
            "agent_registry_refresh_complete",
            discover_ms=round(discover_ms),
            total_ms=round(refresh_ms),
            agent_count=len(new_agent_cache),
            skill_count=len(new_skill_table),
        )

    def get_agent_for_skill(self, skill_id: str) -> Optional[AgentEntry]:
        """Look up the agent entry for a skill.

        Args:
            skill_id: The skill ID to look up

        Returns:
            AgentEntry if found, None otherwise.
        """
        return self._skill_table.get(skill_id)

    def get_all_skills(self) -> List[AgentSkillInfo]:
        """Get metadata for all discovered skills.

        Returns:
            List of AgentSkillInfo across all agents.
        """
        seen: Dict[str, AgentSkillInfo] = {}
        for entry in self._agent_cache.values():
            for skill in entry.skills:
                if skill.skill_id not in seen:
                    seen[skill.skill_id] = skill
        return list(seen.values())

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get Bedrock-format tool specs for all discovered A2A skills.

        Each A2A skill becomes a Bedrock tool with a single `query` parameter.
        The skill description (from the @tool docstring) becomes the tool
        description, allowing the LLM to reason about when to use each tool.

        Returns:
            List of Bedrock toolSpec dicts ready for LLMContext.
        """
        tool_specs = []
        for skill_info in self.get_all_skills():
            spec = _skill_to_bedrock_tool_spec(skill_info)
            tool_specs.append(spec)
        return tool_specs

    def get_skill_count(self) -> int:
        """Get the number of discovered skills."""
        return len(self._skill_table)

    def get_agent_count(self) -> int:
        """Get the number of discovered agents."""
        return len(self._agent_cache)

    @property
    def is_polling(self) -> bool:
        """Whether the registry is actively polling."""
        return self._running

    async def _poll_loop(self, interval_seconds: int) -> None:
        """Background polling loop."""
        # Do an initial refresh immediately
        try:
            await self.refresh()
        except Exception as e:
            logger.error(
                "agent_registry_initial_refresh_failed",
                error=str(e),
                error_type=type(e).__name__,
            )

        while self._running:
            try:
                await asyncio.sleep(interval_seconds)
                if not self._running:
                    break
                await self.refresh()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "agent_registry_poll_error",
                    error=str(e),
                    error_type=type(e).__name__,
                )
                # Continue polling on error


def _skill_to_bedrock_tool_spec(skill: AgentSkillInfo) -> Dict[str, Any]:
    """Convert an A2A skill to a Bedrock toolSpec.

    Since Agent Card skills don't include input schemas (validated in R1 spike),
    each A2A tool uses a single `query: str` parameter. The A2A agent's own
    LLM handles parameter extraction from the natural language query.

    Args:
        skill: Skill metadata from an Agent Card

    Returns:
        Dict in Bedrock toolSpec format.
    """
    return {
        "toolSpec": {
            "name": skill.skill_id,
            "description": skill.description,
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Natural language query for this capability. "
                                "Be specific and include relevant context."
                            ),
                        },
                    },
                    "required": ["query"],
                },
            },
        },
    }
