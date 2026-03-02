#!/usr/bin/env python3
"""Knowledge Base Capability Agent.

A standalone A2A-compliant agent that provides knowledge base search capabilities
via the A2A protocol. Deployed as an independent ECS Fargate service, discovered
by the voice agent via CloudMap.

Uses a DirectToolExecutor to call the KB retrieval function directly, bypassing
the Strands LLM reasoning loop. This eliminates ~2s of latency from the inner
LLM call that was previously used to decide which tool to invoke and to
synthesize results -- both unnecessary for a single-tool agent where the voice
agent's LLM already handles tool selection and response formatting.

The A2AServer is still used for Agent Card generation, skill auto-discovery,
URL handling, and serving -- only the executor is swapped.

Environment variables:
    KB_KNOWLEDGE_BASE_ID: Bedrock Knowledge Base ID (required)
    KB_RETRIEVAL_MAX_RESULTS: Max results per query (default: 3)
    KB_MIN_CONFIDENCE_SCORE: Min confidence threshold (default: 0.3)
    AWS_REGION: AWS region (default: us-east-1)
    LLM_MODEL_ID: Bedrock model for Strands Agent init (default: us.anthropic.claude-haiku-4-5-20251001-v1:0)
    PORT: Server port (default: 8000)
    AGENT_NAME: Agent name for logging (default: knowledge-base)
"""

import asyncio
import json
import os
import sys
import time

import boto3
import requests
import structlog
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, TaskState, TextPart
from cachetools import TTLCache
from strands import Agent, tool
from strands.models import BedrockModel
from strands.multiagent.a2a import A2AServer

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger(__name__)

# Configuration from environment
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
KB_KNOWLEDGE_BASE_ID = os.getenv("KB_KNOWLEDGE_BASE_ID", "")
KB_MAX_RESULTS = int(os.getenv("KB_RETRIEVAL_MAX_RESULTS", "3"))
KB_MIN_CONFIDENCE = float(os.getenv("KB_MIN_CONFIDENCE_SCORE", "0.3"))
LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
PORT = int(os.getenv("PORT", "8000"))

# Bedrock agent runtime client (sync — Strands tools are synchronous)
_bedrock_client = None

# Result cache: avoids redundant KB retrievals for repeated queries
# TTL ensures freshness; maxsize prevents unbounded memory growth
_CACHE_TTL_SECONDS = int(os.getenv("KB_CACHE_TTL_SECONDS", "60"))
_CACHE_MAX_SIZE = int(os.getenv("KB_CACHE_MAX_SIZE", "100"))
_result_cache: TTLCache = TTLCache(maxsize=_CACHE_MAX_SIZE, ttl=_CACHE_TTL_SECONDS)


def _get_task_private_ip() -> str | None:
    """Get this ECS task's private IPv4 address from the metadata endpoint.

    In ECS Fargate, the metadata endpoint provides task network info.
    We use this so the Agent Card advertises a reachable URL instead of 0.0.0.0.

    Returns:
        Private IP string, or None if not running in ECS.
    """
    metadata_uri = os.getenv("ECS_CONTAINER_METADATA_URI_V4")
    if not metadata_uri:
        return None

    try:
        resp = requests.get(f"{metadata_uri}/task", timeout=2)
        resp.raise_for_status()
        task_meta = resp.json()
        # Containers[0].Networks[0].IPv4Addresses[0]
        containers = task_meta.get("Containers", [])
        for container in containers:
            networks = container.get("Networks", [])
            for network in networks:
                addrs = network.get("IPv4Addresses", [])
                if addrs:
                    return addrs[0]
    except Exception as e:
        logger.warning("task_ip_metadata_failed", error=str(e))

    return None


def _get_bedrock_client():
    """Lazy-initialize the Bedrock agent runtime client."""
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client(
            "bedrock-agent-runtime",
            region_name=AWS_REGION,
        )
    return _bedrock_client


@tool
def search_knowledge_base(query: str, max_results: int = 3) -> dict:
    """Search the knowledge base for information about products, policies,
    procedures, or other documentation. Use this when the user asks questions
    that might be answered by company documentation, FAQs, or reference
    materials. Always cite the source when presenting information.

    Args:
        query: Natural language search query. Be specific for better results.
        max_results: Maximum results to return (1-5, default 3).

    Returns:
        Dictionary with search results including content, source, and confidence.
    """
    if not KB_KNOWLEDGE_BASE_ID:
        return {
            "found": False,
            "error": "Knowledge Base is not configured",
            "results": [],
        }

    if not query or not query.strip():
        return {
            "found": False,
            "error": "Search query cannot be empty",
            "results": [],
        }

    # Clamp max_results to valid range
    effective_max = min(max(max_results, 1), 5)

    # Cache lookup: normalize query for consistent cache keys
    cache_key = " ".join(query.lower().split()) + f"|{effective_max}"
    cached = _result_cache.get(cache_key)
    if cached is not None:
        logger.info(
            "kb_cache_hit",
            query=query[:100],
            cache_size=len(_result_cache),
        )
        return cached

    logger.info(
        "kb_searching",
        query=query[:100],
        max_results=effective_max,
        kb_id=KB_KNOWLEDGE_BASE_ID,
    )

    tool_start = time.monotonic()

    try:
        client_start = time.monotonic()
        client = _get_bedrock_client()
        client_ms = (time.monotonic() - client_start) * 1000

        retrieve_start = time.monotonic()
        response = client.retrieve(
            knowledgeBaseId=KB_KNOWLEDGE_BASE_ID,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": effective_max,
                }
            },
        )
        retrieve_ms = (time.monotonic() - retrieve_start) * 1000

        # Parse and filter results
        parse_start = time.monotonic()
        results = []
        for item in response.get("retrievalResults", []):
            score = item.get("score", 0.0)
            if score < KB_MIN_CONFIDENCE:
                continue

            content = item.get("content", {}).get("text", "")
            if not content:
                continue

            # Extract source from S3 location
            source = "Knowledge Base"
            location = item.get("location", {})
            if location.get("type") == "S3":
                s3_uri = location.get("s3Location", {}).get("uri", "")
                if s3_uri:
                    source = s3_uri.split("/")[-1]

            results.append(
                {
                    "content": content,
                    "source": source,
                    "confidence": round(score, 2),
                }
            )

        # Sort by confidence descending
        results.sort(key=lambda r: r["confidence"], reverse=True)
        parse_ms = (time.monotonic() - parse_start) * 1000

        total_ms = (time.monotonic() - tool_start) * 1000

        logger.info(
            "kb_search_complete",
            result_count=len(results),
            pre_filter_count=len(response.get("retrievalResults", [])),
            client_init_ms=round(client_ms, 1),
            retrieve_ms=round(retrieve_ms, 1),
            parse_ms=round(parse_ms, 1),
            total_ms=round(total_ms, 1),
        )

        if not results:
            result = {
                "found": False,
                "message": "No relevant information found in the knowledge base",
                "results": [],
            }
            _result_cache[cache_key] = result
            return result

        result = {
            "found": True,
            "result_count": len(results),
            "results": results,
        }
        _result_cache[cache_key] = result
        return result

    except Exception as e:
        total_ms = (time.monotonic() - tool_start) * 1000
        logger.exception(
            "kb_search_failed", error=str(e), elapsed_ms=round(total_ms, 1)
        )
        return {
            "found": False,
            "error": f"Knowledge base search failed: {str(e)}",
            "results": [],
        }


class DirectToolExecutor(AgentExecutor):
    """A2A executor that calls the KB tool directly, bypassing LLM reasoning.

    For a single-tool agent like the KB agent, the inner Strands LLM call adds
    ~2s of latency to: (1) decide to call the only available tool, and (2)
    synthesize the results. Both are unnecessary since the voice agent's LLM
    already made the tool selection and will synthesize the response for speech.

    This executor implements the a2a-sdk AgentExecutor interface, so it's fully
    A2A-protocol compliant. The voice agent can't tell the difference.
    """

    def __init__(self, tool_func):
        """Initialize with the tool function to call directly.

        Args:
            tool_func: The @tool-decorated function (search_knowledge_base).
        """
        self._tool_func = tool_func

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Execute the tool directly without LLM reasoning.

        Extracts the query from the A2A message, calls the tool function,
        and returns the result as an A2A artifact.
        """
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.update_status(TaskState.working)

        try:
            # Extract text from the incoming A2A message
            query = context.get_user_input()
            if not query or not query.strip():
                msg = updater.new_agent_message(
                    [
                        Part(
                            root=TextPart(
                                text='{"found": false, "error": "Empty query", "results": []}'
                            )
                        )
                    ]
                )
                await updater.complete(message=msg)
                return

            start = time.monotonic()

            # Call the tool directly in a thread (it's synchronous)
            result = await asyncio.to_thread(self._tool_func, query=query)

            elapsed_ms = (time.monotonic() - start) * 1000
            logger.info(
                "direct_tool_execution",
                elapsed_ms=round(elapsed_ms, 1),
                query=query[:100],
            )

            # Format as JSON text for the A2A response
            result_text = json.dumps(result, default=str)
            msg = updater.new_agent_message([Part(root=TextPart(text=result_text))])
            await updater.complete(message=msg)

        except Exception as e:
            logger.exception("direct_tool_execution_failed", error=str(e))
            error_text = json.dumps(
                {
                    "found": False,
                    "error": f"Tool execution failed: {str(e)}",
                    "results": [],
                }
            )
            msg = updater.new_agent_message([Part(root=TextPart(text=error_text))])
            await updater.failed(message=msg)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Cancel a running task."""
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel()


def main():
    """Start the Knowledge Base A2A agent server."""
    if not KB_KNOWLEDGE_BASE_ID:
        logger.warning("kb_id_not_set", note="agent will return errors for searches")

    # --- Warm-up: pre-initialize boto3 client to avoid first-call cold start ---
    warmup_start = time.monotonic()
    try:
        _get_bedrock_client()
        logger.info(
            "boto3_client_warmup_complete",
            elapsed_ms=round((time.monotonic() - warmup_start) * 1000, 1),
        )
    except Exception as e:
        logger.warning(
            "boto3_client_warmup_failed", error=str(e), note="will retry on first call"
        )

    # Create the Strands Agent -- still needed for A2AServer to auto-generate
    # the Agent Card, skills list, and URL handling. The Agent's LLM is NOT
    # used for request processing (DirectToolExecutor bypasses it).
    model = BedrockModel(
        model_id=LLM_MODEL_ID,
        region_name=AWS_REGION,
    )

    agent = Agent(
        name="Knowledge Base Agent",
        description=(
            "Searches enterprise knowledge base for product, policy, "
            "and procedure information. Use this agent when users ask "
            "about company documentation, FAQs, or reference materials."
        ),
        model=model,
        tools=[search_knowledge_base],
        callback_handler=None,
    )

    # Determine the reachable URL for the Agent Card.
    # In ECS Fargate, the server binds to 0.0.0.0 but must advertise the
    # task's private IP so other services can reach it via A2A protocol.
    task_ip = _get_task_private_ip()
    http_url = f"http://{task_ip}:{PORT}/" if task_ip else None

    server = A2AServer(
        agent=agent,
        host="0.0.0.0",
        port=PORT,
        http_url=http_url,
        version="0.1.0",
    )

    # --- Swap the executor: bypass the Strands LLM reasoning loop ---
    # A2AServer creates a StrandsA2AExecutor that calls agent.stream_async(),
    # which invokes the Haiku LLM (~2s overhead). We replace it with
    # DirectToolExecutor that calls search_knowledge_base() directly.
    server.request_handler.agent_executor = DirectToolExecutor(search_knowledge_base)

    logger.info("kb_agent_starting", port=PORT, mode="direct_tool")
    logger.info("kb_config", kb_id=KB_KNOWLEDGE_BASE_ID or "(not configured)")
    logger.info("agent_card_url", url=http_url or f"http://0.0.0.0:{PORT}/")
    logger.info("llm_bypassed", note="tool calls execute directly for lower latency")
    # Disable uvicorn access logs -- CloudMap polls /.well-known/agent-card.json
    # every 30s, producing ~2,880 noise lines/day. Our structlog captures all
    # meaningful request events (tool calls, errors) already.
    server.serve(access_log=False)


if __name__ == "__main__":
    main()
