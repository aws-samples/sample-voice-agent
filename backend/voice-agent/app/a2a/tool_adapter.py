"""A2A to Pipecat tool adapter.

Bridges A2A capability agents into Pipecat's tool calling flow by creating
handler functions that match Pipecat's register_function signature.

When the LLM emits a tool_use for an A2A skill, the adapter:
1. Checks the response cache for a cached result
2. Calls the remote agent via A2AAgent.invoke_async()
3. Extracts text from AgentResult.message content blocks
4. Caches the response for future identical queries
5. Returns the result via Pipecat's result_callback()

Usage:
    handler = create_a2a_tool_handler("search_knowledge_base", a2a_agent)
    llm.register_function(function_name="search_knowledge_base", handler=handler)
"""

import asyncio
import os
import time
from typing import Any, Callable, Dict, Optional

import structlog
from cachetools import TTLCache
from pipecat.services.llm_service import FunctionCallParams

from app.tools.result_summarizer import is_result_logging_enabled, summarize_tool_result

logger = structlog.get_logger(__name__)

# A2A adapter-level response cache configuration
_A2A_CACHE_TTL = int(os.getenv("A2A_CACHE_TTL_SECONDS", "60"))
_A2A_CACHE_MAX_SIZE = int(os.getenv("A2A_CACHE_MAX_SIZE", "100"))


def _normalize_query(query: str) -> str:
    """Normalize a query string for use as a cache key.

    Lowercases, strips whitespace, and collapses internal spaces.
    """
    return " ".join(query.lower().split())


def create_a2a_tool_handler(
    skill_id: str,
    agent: Any,  # A2AAgent instance
    timeout_seconds: float = 30.0,
    collector: Optional[Any] = None,  # MetricsCollector
    cache: Optional[TTLCache] = None,  # Optional shared cache
    category: str = "a2a",  # Metrics category (prefer resolve_tool_category)
) -> Callable:
    """Create a Pipecat-compatible tool handler for an A2A skill.

    Returns an async function matching Pipecat's register_function handler
    signature that routes tool calls to a remote A2A agent.

    Args:
        skill_id: The skill/tool name as seen by the LLM
        agent: A2AAgent instance for the remote capability agent
        timeout_seconds: Maximum time to wait for A2A response
        collector: Optional MetricsCollector for A2A call metrics
        cache: Optional TTLCache for response caching. If None, a per-handler
            cache is created using A2A_CACHE_TTL_SECONDS and A2A_CACHE_MAX_SIZE
            env vars.
        category: Metrics category string for this tool. Use
            ``resolve_tool_category(agent_name).value`` to derive a
            meaningful category from the agent's name. Defaults to
            ``"a2a"`` for backward compatibility.

    Returns:
        Async handler function for use with llm.register_function()
    """
    # Each handler gets its own cache if none is shared
    response_cache = (
        cache
        if cache is not None
        else TTLCache(maxsize=_A2A_CACHE_MAX_SIZE, ttl=_A2A_CACHE_TTL)
    )

    async def a2a_tool_handler(params: FunctionCallParams) -> None:
        """Pipecat function handler that routes to A2A agent."""
        start_time = time.monotonic()

        # Extract query from args (our standard single-parameter pattern)
        query = params.arguments.get("query", "")
        if not query:
            # Fallback: concatenate all string args as a query
            query = " ".join(str(v) for v in params.arguments.values() if v)

        logger.info(
            "a2a_tool_call_start",
            skill_id=skill_id,
            tool_call_id=params.tool_call_id,
            query=query[:200],
        )

        # --- Cache lookup ---
        cache_key = f"{skill_id}|{_normalize_query(query)}"
        cached_response = response_cache.get(cache_key)
        if cached_response is not None:
            cache_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "a2a_tool_call_cache_hit",
                skill_id=skill_id,
                cache_ms=round(cache_ms, 1),
                cache_size=len(response_cache),
            )
            if collector:
                try:
                    collector.record_tool_execution(
                        tool_name=skill_id,
                        category=category,
                        status="cache_hit",
                        execution_time_ms=cache_ms,
                    )
                except Exception as e:
                    logger.debug(
                        "a2a_metrics_recording_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        skill_id=skill_id,
                        status="cache_hit",
                    )
            await params.result_callback(cached_response)
            return

        try:
            # --- A2A invocation with timing breakdown ---
            invoke_start = time.monotonic()
            result = await asyncio.wait_for(
                agent.invoke_async(query),
                timeout=timeout_seconds,
            )
            invoke_ms = (time.monotonic() - invoke_start) * 1000

            # Extract text from AgentResult.message content blocks
            extract_start = time.monotonic()
            response_text = extract_text_from_result(result)
            extract_ms = (time.monotonic() - extract_start) * 1000

            elapsed_ms = (time.monotonic() - start_time) * 1000

            # Build log kwargs with optional result summary
            log_kwargs = {
                "skill_id": skill_id,
                "elapsed_ms": round(elapsed_ms),
                "invoke_ms": round(invoke_ms),
                "extract_ms": round(extract_ms, 1),
                "response_length": len(response_text),
            }

            result_summary = None
            if is_result_logging_enabled():
                try:
                    result_summary = summarize_tool_result(
                        response_text, tool_name=skill_id
                    )
                except Exception:
                    pass

            if result_summary is not None:
                log_kwargs["result_summary"] = result_summary

            logger.info("a2a_tool_call_success", **log_kwargs)

            if result_summary is not None:
                logger.debug(
                    "a2a_tool_result_detail",
                    skill_id=skill_id,
                    result_content=response_text,
                )

            # Cache the successful response
            response_cache[cache_key] = response_text

            # Emit metrics with correct signature
            if collector:
                try:
                    collector.record_tool_execution(
                        tool_name=skill_id,
                        category=category,
                        status="success",
                        execution_time_ms=elapsed_ms,
                    )
                except Exception as e:
                    logger.debug(
                        "a2a_metrics_recording_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        skill_id=skill_id,
                        status="success",
                    )

            # Return result to Pipecat's LLM via result_callback
            await params.result_callback(response_text)

        except asyncio.TimeoutError:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.warning(
                "a2a_tool_call_timeout",
                skill_id=skill_id,
                timeout_seconds=timeout_seconds,
                elapsed_ms=round(elapsed_ms),
            )

            if collector:
                try:
                    collector.record_tool_execution(
                        tool_name=skill_id,
                        category=category,
                        status="timeout",
                        execution_time_ms=elapsed_ms,
                    )
                except Exception as e:
                    logger.debug(
                        "a2a_metrics_recording_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        skill_id=skill_id,
                        status="timeout",
                    )

            await params.result_callback(
                {
                    "error": True,
                    "error_code": "A2A_TIMEOUT",
                    "error_message": (
                        f"The {skill_id} service did not respond within "
                        f"{timeout_seconds} seconds. Please try again."
                    ),
                }
            )

        except asyncio.CancelledError:
            # Barge-in — pipeline is cancelling this tool call
            logger.info(
                "a2a_tool_call_cancelled",
                skill_id=skill_id,
            )
            raise  # Re-raise so pipeline handles cancellation

        except Exception as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            logger.error(
                "a2a_tool_call_error",
                skill_id=skill_id,
                error=str(e),
                error_type=type(e).__name__,
                elapsed_ms=round(elapsed_ms),
            )

            if collector:
                try:
                    collector.record_tool_execution(
                        tool_name=skill_id,
                        category="a2a",
                        status="error",
                        execution_time_ms=elapsed_ms,
                    )
                except Exception as e:
                    logger.debug(
                        "a2a_metrics_recording_failed",
                        error=str(e),
                        error_type=type(e).__name__,
                        skill_id=skill_id,
                        status="error",
                    )

            await params.result_callback(
                {
                    "error": True,
                    "error_code": "A2A_ERROR",
                    "error_message": (
                        f"Error calling {skill_id}: {type(e).__name__}: {str(e)}"
                    ),
                }
            )

    return a2a_tool_handler


def extract_text_from_result(result: Any) -> str:
    """Extract text content from an A2AAgent's AgentResult.

    AgentResult.message has the format:
        {"role": "assistant", "content": [{"text": "..."}, ...]}

    This function concatenates all text blocks from the content array.

    Args:
        result: AgentResult from A2AAgent.invoke_async()

    Returns:
        Concatenated text string from all content blocks.
    """
    if not hasattr(result, "message") or not result.message:
        return str(result)

    message = result.message

    if not isinstance(message, dict):
        return str(message)

    content = message.get("content", [])
    if not content:
        return ""

    text_parts = []
    for block in content:
        if isinstance(block, dict) and "text" in block:
            text_parts.append(block["text"])

    return "\n".join(text_parts) if text_parts else str(result)
