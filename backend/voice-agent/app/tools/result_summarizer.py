"""Tool result summarization and PII redaction for structured logging.

This module provides utilities to create concise, privacy-safe summaries
of tool execution results for inclusion in structured log events.

When the ``enable_tool_result_logging`` feature flag is active, tool
results are summarized at INFO level (truncated to a configurable max
length) and optionally logged in full at DEBUG level.

Usage:
    from app.tools.result_summarizer import summarize_tool_result, is_result_logging_enabled

    if is_result_logging_enabled():
        summary = summarize_tool_result(result_content, max_chars=500)
        logger.info("tool_execution_complete", result_summary=summary)
"""

import json
import os
import re
from typing import Any, Dict, Optional, Union

import structlog

logger = structlog.get_logger(__name__)

# Default max characters for result summaries
_DEFAULT_MAX_CHARS = int(os.getenv("TOOL_RESULT_LOG_MAX_CHARS", "500"))

# PII redaction patterns
_PII_PATTERNS = [
    # Email addresses
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "***@***.***"),
    # US phone numbers (various formats)
    (
        re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        "***-***-****",
    ),
    # SSN (###-##-####)
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "***-**-****"),
    # Account numbers (ACCT-######## or similar)
    (
        re.compile(r"\b(ACCT|ACC|ACCOUNT)[-#]?\d{6,}\b", re.IGNORECASE),
        r"\1-********",
    ),
    # Credit card numbers (basic patterns, 13-19 digits with optional separators)
    (
        re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{1,7}\b"),
        "****-****-****-****",
    ),
]


def is_result_logging_enabled() -> bool:
    """Check if tool result logging is enabled via SSM config.

    Falls back to the ``ENABLE_TOOL_RESULT_LOGGING`` environment variable
    if the config service is not available.

    Returns:
        True if tool result logging is enabled.
    """
    try:
        from app.services import get_config_service

        svc = get_config_service()
        if svc.is_configured():
            return svc.config.features.enable_tool_result_logging
    except Exception:
        pass

    # Env var fallback
    return os.getenv("ENABLE_TOOL_RESULT_LOGGING", "false").lower() == "true"


def redact_pii(text: str) -> str:
    """Apply regex-based PII redaction to text.

    Replaces common PII patterns (email, phone, SSN, account numbers,
    credit card numbers) with masked placeholders.

    Args:
        text: Input text that may contain PII.

    Returns:
        Text with PII patterns replaced by placeholders.
    """
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def summarize_tool_result(
    content: Union[Dict[str, Any], str, None],
    max_chars: int = _DEFAULT_MAX_CHARS,
    tool_name: Optional[str] = None,
) -> Optional[str]:
    """Create a concise, PII-safe summary of a tool result.

    Applies type-specific extraction for known tool types, then
    falls back to a generic JSON truncation. All output is passed
    through PII redaction.

    Args:
        content: The tool result content (dict for local tools,
            string for A2A response text, or None).
        max_chars: Maximum characters for the summary.
        tool_name: Optional tool/skill name for type-specific extraction.

    Returns:
        Summarized string, or None if content is empty.
    """
    if content is None:
        return None

    # Try type-specific extractors first
    if tool_name and isinstance(content, (dict, str)):
        specific = _extract_specific(content, tool_name)
        if specific is not None:
            return redact_pii(_truncate(specific, max_chars))

    # Generic fallback
    if isinstance(content, dict):
        text = json.dumps(content, default=str, ensure_ascii=False)
    elif isinstance(content, str):
        text = content
    else:
        text = str(content)

    return redact_pii(_truncate(text, max_chars))


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, adding ellipsis if needed."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _extract_specific(
    content: Union[Dict[str, Any], str], tool_name: str
) -> Optional[str]:
    """Extract structured summary for known tool types.

    Returns None if no specific extractor matches, falling through
    to the generic summarizer.
    """
    name_lower = tool_name.lower()

    if "knowledge_base" in name_lower or "search_kb" in name_lower:
        return _extract_kb_summary(content)
    if "lookup_customer" in name_lower or "verify_account" in name_lower:
        return _extract_crm_summary(content)
    if "appointment" in name_lower:
        return _extract_appointment_summary(content)
    if "get_current_time" in name_lower:
        return _extract_time_summary(content)

    return None


def _extract_kb_summary(content: Union[Dict[str, Any], str]) -> Optional[str]:
    """Extract KB search summary: document titles, confidence, snippets."""
    if isinstance(content, str):
        # A2A text response -- extract first few lines as summary
        lines = content.strip().split("\n")
        preview = " | ".join(line.strip() for line in lines[:3] if line.strip())
        if len(lines) > 3:
            preview += f" ... (+{len(lines) - 3} more lines)"
        return f"KB result: {preview}" if preview else None

    # Dict-based result (local tool pattern)
    parts = []
    if "documents" in content:
        docs = content["documents"]
        for doc in docs[:3]:
            title = doc.get("title", doc.get("source", "untitled"))
            score = doc.get("confidence", doc.get("score"))
            snippet = doc.get("snippet", doc.get("text", ""))[:100]
            entry = f"{title}"
            if score is not None:
                entry += f" (conf={score:.2f})"
            if snippet:
                entry += f": {snippet}"
            parts.append(entry)
        if len(docs) > 3:
            parts.append(f"+{len(docs) - 3} more")
    if parts:
        return "KB results: " + " | ".join(parts)

    return None


def _extract_crm_summary(content: Union[Dict[str, Any], str]) -> Optional[str]:
    """Extract CRM lookup summary: customer ID, status, key fields."""
    if isinstance(content, str):
        lines = content.strip().split("\n")
        preview = " | ".join(line.strip() for line in lines[:3] if line.strip())
        return f"CRM result: {preview}" if preview else None

    parts = []
    if "customer_id" in content:
        parts.append(f"id={content['customer_id']}")
    if "verified" in content:
        parts.append(f"verified={content['verified']}")
    if "status" in content:
        parts.append(f"status={content['status']}")
    if "name" in content:
        parts.append(f"name={content['name']}")

    if parts:
        return "CRM: " + ", ".join(parts)

    return None


def _extract_appointment_summary(
    content: Union[Dict[str, Any], str],
) -> Optional[str]:
    """Extract appointment summary: date, time, type, ID."""
    if isinstance(content, str):
        lines = content.strip().split("\n")
        preview = " | ".join(line.strip() for line in lines[:3] if line.strip())
        return f"Appointment result: {preview}" if preview else None

    parts = []
    if "appointment_id" in content:
        parts.append(f"id={content['appointment_id']}")
    if "date" in content:
        parts.append(f"date={content['date']}")
    if "time" in content:
        parts.append(f"time={content['time']}")
    if "type" in content:
        parts.append(f"type={content['type']}")
    if "status" in content:
        parts.append(f"status={content['status']}")

    if parts:
        return "Appointment: " + ", ".join(parts)

    return None


def _extract_time_summary(content: Union[Dict[str, Any], str]) -> Optional[str]:
    """Extract time tool summary."""
    if isinstance(content, dict):
        time_str = content.get("current_time", "")
        date_str = content.get("current_date", "")
        if time_str or date_str:
            return f"Time: {date_str} {time_str}".strip()

    return None
