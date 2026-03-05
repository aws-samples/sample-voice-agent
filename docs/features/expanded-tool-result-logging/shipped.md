---
id: expanded-tool-result-logging
name: Expanded Tool Result Logging
type: enhancement
priority: P2
effort: Medium
impact: Medium
status: shipped
created: 2026-03-05
started: 2026-03-05
shipped: 2026-03-05
---

# Shipped: Expanded Tool Result Logging

## Summary

Added tool result content to structured log events so operators can see *what* A2A tools returned, not just that they were called. A truncated, PII-redacted `result_summary` (max 500 chars) is added to INFO-level log events (`tool_execution`, `a2a_tool_call_success`, `flow_a2a_call_success`). Full `result_content` is available at DEBUG level. Feature-gated via SSM parameter `/voice-agent/config/enable-tool-result-logging` (default `false`).

## What Was Built

### Result Summarizer (`app/tools/result_summarizer.py`)

- Truncation to configurable max chars (default 500)
- Regex-based PII redaction for email, phone, SSN, and account numbers
- Consistent summarization across local and A2A tool results

### Log Event Enrichment

- `tool_execution` events now include `result_summary` at INFO level
- `a2a_tool_call_success` and `flow_a2a_call_success` events include `result_summary` at INFO level
- Full `result_content` logged at DEBUG level for all tool types
- SSM parameter `/voice-agent/config/enable-tool-result-logging` controls the feature
- `TOOL_RESULT_LOG_MAX_CHARS` env var controls truncation length

### Frontend Integration

- Timeline event component shows inline result preview for tool executions
- KB searches show document titles, snippets, and confidence scores
- CRM lookups show customer name and ID
- Appointment tools show booking details

## Files Changed

### New Files
- `app/tools/result_summarizer.py` -- summarization + PII redaction utility
- `tests/test_result_summarizer.py` -- 38 unit tests

### Modified Files
- `app/tools/builtin/executor.py` -- local tool result logging
- `app/observability.py` -- ConversationObserver result logging
- `app/a2a/tool_adapter.py` -- A2A tool result logging
- `app/flows/flow_config.py` -- Flows A2A tool result logging
- `app/services/config_service.py` -- SSM parameter for feature gate
- `infrastructure/src/constructs/voice-agent-monitoring-construct.ts` -- SSM parameter
- `frontend/call-flow-visualizer/src/components/TimelineEvent.tsx` -- inline preview
- `AGENTS.md` -- documentation updates

## Quality Gates

### QA Validation: PASS
- 38 unit tests for result summarizer -- all passing
- PII redaction verified for email, phone, SSN, account number patterns
- Truncation verified at boundary conditions
- Feature gate verified: disabled by default, no log changes when off

### Security Review: PASS WITH NOTES
- PII redaction uses regex patterns -- not exhaustive but covers common formats
- Result content at DEBUG level may contain sensitive data; DEBUG logging should only be enabled in controlled environments
- Feature is off by default, requiring explicit opt-in via SSM
