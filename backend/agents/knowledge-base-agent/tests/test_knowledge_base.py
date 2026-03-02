"""Tests for the Knowledge Base agent (search tool + DirectToolExecutor).

Covers the search_knowledge_base tool function with mocked Bedrock calls,
caching behavior, and the DirectToolExecutor async execution.
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add agent source directory for import resolution
AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

# Patch env vars before importing main — it reads them at module level
with patch.dict(
    "os.environ",
    {
        "KB_KNOWLEDGE_BASE_ID": "kb-test-123",
        "AWS_REGION": "us-east-1",
        "KB_RETRIEVAL_MAX_RESULTS": "3",
        "KB_MIN_CONFIDENCE_SCORE": "0.3",
        "KB_CACHE_TTL_SECONDS": "60",
        "KB_CACHE_MAX_SIZE": "100",
    },
):
    # Also mock boto3.client so it doesn't try to actually connect
    with patch("boto3.client") as _mock_boto:
        from main import (  # noqa: E402
            DirectToolExecutor,
            search_knowledge_base,
            _result_cache,
        )


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_RETRIEVAL_RESPONSE = {
    "retrievalResults": [
        {
            "content": {"text": "Our return policy allows returns within 30 days."},
            "score": 0.92,
            "location": {
                "type": "S3",
                "s3Location": {"uri": "s3://bucket/docs/return-policy.pdf"},
            },
        },
        {
            "content": {"text": "Shipping takes 3-5 business days."},
            "score": 0.75,
            "location": {
                "type": "S3",
                "s3Location": {"uri": "s3://bucket/docs/shipping-faq.pdf"},
            },
        },
        {
            "content": {"text": "Irrelevant low-confidence result."},
            "score": 0.1,  # Below threshold
            "location": {
                "type": "S3",
                "s3Location": {"uri": "s3://bucket/docs/other.pdf"},
            },
        },
    ]
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the result cache before each test."""
    _result_cache.clear()
    yield
    _result_cache.clear()


@pytest.fixture
def mock_bedrock():
    """Mock the Bedrock agent runtime client."""
    mock_client = MagicMock()
    with (
        patch("main._bedrock_client", mock_client),
        patch("main._get_bedrock_client", return_value=mock_client),
    ):
        yield mock_client


# ---------------------------------------------------------------------------
# search_knowledge_base tool
# ---------------------------------------------------------------------------


class TestSearchKnowledgeBase:
    def test_returns_filtered_results(self, mock_bedrock):
        mock_bedrock.retrieve.return_value = SAMPLE_RETRIEVAL_RESPONSE

        result = search_knowledge_base(query="return policy")

        assert result["found"] is True
        assert result["result_count"] == 2  # Third result filtered by score
        assert result["results"][0]["confidence"] == 0.92
        assert result["results"][0]["source"] == "return-policy.pdf"

    def test_results_sorted_by_confidence(self, mock_bedrock):
        mock_bedrock.retrieve.return_value = SAMPLE_RETRIEVAL_RESPONSE

        result = search_knowledge_base(query="shipping")

        confidences = [r["confidence"] for r in result["results"]]
        assert confidences == sorted(confidences, reverse=True)

    def test_empty_query(self):
        result = search_knowledge_base(query="")
        assert result["found"] is False
        assert "empty" in result["error"].lower()

    def test_whitespace_query(self):
        result = search_knowledge_base(query="   ")
        assert result["found"] is False

    def test_kb_not_configured(self, mock_bedrock):
        with patch("main.KB_KNOWLEDGE_BASE_ID", ""):
            result = search_knowledge_base(query="test")
        assert result["found"] is False
        assert "not configured" in result["error"].lower()

    def test_max_results_clamped_to_range(self, mock_bedrock):
        mock_bedrock.retrieve.return_value = {"retrievalResults": []}

        # Should clamp to 5
        search_knowledge_base(query="test", max_results=100)
        call_args = mock_bedrock.retrieve.call_args
        num_results = call_args[1]["retrievalConfiguration"][
            "vectorSearchConfiguration"
        ]["numberOfResults"]
        assert num_results == 5

        # Should clamp to 1
        search_knowledge_base(query="test2", max_results=0)
        call_args = mock_bedrock.retrieve.call_args
        num_results = call_args[1]["retrievalConfiguration"][
            "vectorSearchConfiguration"
        ]["numberOfResults"]
        assert num_results == 1

    def test_no_results_above_threshold(self, mock_bedrock):
        mock_bedrock.retrieve.return_value = {
            "retrievalResults": [
                {"content": {"text": "Low score result"}, "score": 0.1},
            ]
        }

        result = search_knowledge_base(query="obscure topic")

        assert result["found"] is False
        assert result["results"] == []

    def test_empty_content_skipped(self, mock_bedrock):
        mock_bedrock.retrieve.return_value = {
            "retrievalResults": [
                {"content": {"text": ""}, "score": 0.9},
                {"content": {"text": "Real content"}, "score": 0.8},
            ]
        }

        result = search_knowledge_base(query="test")

        assert result["result_count"] == 1
        assert result["results"][0]["content"] == "Real content"

    def test_non_s3_location_defaults_source(self, mock_bedrock):
        mock_bedrock.retrieve.return_value = {
            "retrievalResults": [
                {
                    "content": {"text": "Some content"},
                    "score": 0.9,
                    "location": {"type": "WEB"},
                },
            ]
        }

        result = search_knowledge_base(query="test")

        assert result["results"][0]["source"] == "Knowledge Base"

    def test_bedrock_exception(self, mock_bedrock):
        mock_bedrock.retrieve.side_effect = Exception("Bedrock unavailable")

        result = search_knowledge_base(query="test")

        assert result["found"] is False
        assert "failed" in result["error"].lower()

    def test_caching(self, mock_bedrock):
        mock_bedrock.retrieve.return_value = SAMPLE_RETRIEVAL_RESPONSE

        # First call — hits Bedrock
        result1 = search_knowledge_base(query="return policy")
        assert mock_bedrock.retrieve.call_count == 1

        # Second identical call — served from cache
        result2 = search_knowledge_base(query="return policy")
        assert mock_bedrock.retrieve.call_count == 1  # Still 1
        assert result1 == result2

    def test_cache_key_normalizes_whitespace(self, mock_bedrock):
        mock_bedrock.retrieve.return_value = SAMPLE_RETRIEVAL_RESPONSE

        search_knowledge_base(query="return  policy")
        search_knowledge_base(query="return policy")

        # Both should produce the same normalized cache key
        assert mock_bedrock.retrieve.call_count == 1


# ---------------------------------------------------------------------------
# DirectToolExecutor
# ---------------------------------------------------------------------------


class TestDirectToolExecutor:
    def _make_context(self, query: str):
        """Create a mock RequestContext with the given user input."""
        ctx = MagicMock()
        ctx.task_id = "task-1"
        ctx.context_id = "ctx-1"
        ctx.get_user_input.return_value = query
        return ctx

    @pytest.mark.asyncio
    async def test_execute_returns_json(self, mock_bedrock):
        mock_bedrock.retrieve.return_value = SAMPLE_RETRIEVAL_RESPONSE

        tool_func = MagicMock(
            side_effect=lambda **kwargs: {
                "found": True,
                "result_count": 2,
                "results": [
                    {"content": "test", "source": "doc.pdf", "confidence": 0.9}
                ],
            }
        )

        executor = DirectToolExecutor(tool_func)
        event_queue = AsyncMock()
        event_queue.enqueue_event = AsyncMock()
        ctx = self._make_context("return policy")

        await executor.execute(ctx, event_queue)

        tool_func.assert_called_once_with(query="return policy")

    @pytest.mark.asyncio
    async def test_execute_empty_query(self):
        executor = DirectToolExecutor(lambda **kwargs: {})
        event_queue = AsyncMock()
        event_queue.enqueue_event = AsyncMock()
        ctx = self._make_context("")

        await executor.execute(ctx, event_queue)

        # Should complete (not crash) with an error response

    @pytest.mark.asyncio
    async def test_execute_tool_exception(self):
        def failing_tool(**kwargs):
            raise RuntimeError("boom")

        executor = DirectToolExecutor(failing_tool)
        event_queue = AsyncMock()
        event_queue.enqueue_event = AsyncMock()
        ctx = self._make_context("test query")

        # Should not raise — errors are handled internally
        await executor.execute(ctx, event_queue)

    @pytest.mark.asyncio
    async def test_cancel(self):
        executor = DirectToolExecutor(lambda **kwargs: {})
        event_queue = AsyncMock()
        event_queue.enqueue_event = AsyncMock()
        ctx = self._make_context("test")

        # Should not raise
        await executor.cancel(ctx, event_queue)
