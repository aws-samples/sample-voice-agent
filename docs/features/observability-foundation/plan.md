---
started: 2026-01-26
---

# Implementation Plan: Observability Foundation

## Overview

Add foundational observability capabilities to the voice pipeline: correlation IDs for tracing, call summaries for quick debugging, and error categorization for pattern detection.

## Implementation Steps

- [x] Step 1: Add correlation ID generation and context binding
  - Generate UUID in `start_call()` when a new call begins
  - Use structlog's `bind()` to add `call_id` to all subsequent log entries
  - Pass `call_id` through to `_run_pipeline()` and `create_voice_pipeline()`

- [x] Step 2: Add call metrics tracking
  - Track call start time with `time.monotonic()`
  - Track turn count (increment on each user/assistant exchange)
  - Track completion status (completed, cancelled, error)

- [x] Step 3: Add call summary logging
  - In `_run_pipeline()` finally block, log a `call_summary` event
  - Include: call_id, duration_seconds, turn_count, completion_status, error_type (if any)

- [x] Step 4: Add error categorization
  - Create error category constants: `stt_error`, `llm_error`, `tts_error`, `transport_error`, `config_error`
  - Wrap service operations to catch and categorize exceptions
  - Add `error_category` field to error logs

- [x] Step 5: Add tests for observability features
  - Test that correlation IDs are generated and bound
  - Test that call summaries include required fields
  - Test error categorization for different exception types

## Technical Decisions

1. **UUID for call_id**: Using `uuid.uuid4()` for uniqueness across distributed systems
2. **structlog context binding**: Leverages structlog's built-in context mechanism rather than passing IDs manually
3. **monotonic time**: Using `time.monotonic()` for duration to avoid clock drift issues
4. **Error categories as constants**: Enables filtering/alerting in CloudWatch Logs Insights

## Files to Modify

| File | Changes |
|------|---------|
| `backend/voice-agent/app/service_main.py` | Add correlation ID, call metrics, call summary, error categorization |
| `backend/voice-agent/app/pipeline_ecs.py` | Receive correlation ID context, categorize pipeline errors |

## Testing Strategy

- Unit tests for error categorization logic
- Integration tests verifying log output contains expected fields
- Manual verification with CloudWatch Logs Insights queries

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Log volume increase | Call summary is single log per call; correlation ID adds minimal overhead |
| Breaking existing log consumers | Changes are additive; existing fields preserved |

## Example Log Output

```json
{
  "timestamp": "2026-01-26T10:00:00.000Z",
  "event": "call_summary",
  "call_id": "550e8400-e29b-41d4-a716-446655440000",
  "session_id": "session-123",
  "duration_seconds": 45.2,
  "turn_count": 6,
  "completion_status": "completed",
  "error_category": null
}
```
