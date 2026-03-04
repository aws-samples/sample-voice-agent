---
shipped: 2026-01-26
---

# Shipped: Observability Foundation

## Summary

Added foundational observability capabilities to the voice pipeline: correlation IDs for tracing, call summaries for quick debugging, and error categorization for pattern detection.

## Key Changes

- **Correlation ID**: UUID generated per call, bound to structlog context via `contextvars`
- **Call Summary**: Logged in `finally` block with duration, turn count, completion status
- **Error Categorization**: 6 categories (STT, LLM, TTS, TRANSPORT, CONFIG, UNKNOWN)
- **Tests**: 14 unit tests for error categorization logic

## Files Modified

| File | Changes |
|------|---------|
| `backend/voice-agent/app/service_main.py` | Added `ErrorCategory`, `categorize_error()`, correlation ID binding, call metrics, call summary |
| `backend/voice-agent/tests/test_observability.py` | New test file for error categorization |
| `backend/voice-agent/Containerfile` | Symlink to Dockerfile for finch compatibility |

## Testing

- Unit tests for error categorization (14 tests)
- Deployed to ECS in account 972801262139
- Verified with real phone call - confirmed `call_summary` log with all fields:
  ```json
  {
    "event": "call_summary",
    "call_id": "94aa6851-00d5-473d-b50c-fa38a46b249c",
    "duration_seconds": 26.93,
    "completion_status": "completed",
    "error_category": null
  }
  ```

## CloudWatch Logs Insights Query

```sql
fields @timestamp, call_id, event, duration_seconds, completion_status, error_category
| filter event = "call_summary"
| sort @timestamp desc
| limit 100
```

## Notes

- `turn_count` remains 0 - tracking requires hooking into pipeline events (see `observability-turn-tracking` backlog item)
- All log events now include `call_id` and `session_id` for filtering
