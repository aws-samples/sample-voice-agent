---
id: log-analysis
name: Log Analysis
type: tech-debt
priority: P1
effort: Medium
impact: High
status: shipped
shipped: 2026-02-27
---

# Log Analysis - Shipped

## Summary

Completed a comprehensive codebase-wide audit and remediation of logging issues. Fixed real bugs masked by noisy logs, standardized structured logging context, and corrected log levels across the voice agent backend.

## What Was Delivered

### Phase 1: Real Bug Fixes

1. **Task Protection Retry Logic** (`task_protection.py`)
   - Added retry logic to `renew_if_protected()` with 3 attempts and exponential backoff
   - Added consecutive failure tracking with escalation to ERROR after 3+ failures
   - Prevents silent protection lapse during transient network failures

2. **A2A Registry Grace Period** (`a2a/registry.py`)
   - Added 3-poll grace period (~90s) before clearing routing table on empty CloudMap responses
   - Carries forward cached agent entries on transient card fetch failures
   - Survives temporary CloudMap/agent outages without dropping tools

3. **Heartbeat Failure Escalation** (`session_tracker.py`)
   - Added consecutive failure counter for heartbeat loop
   - Escalates WARNING -> ERROR after 5+ consecutive failures (~2.5 min)
   - Enables CloudWatch alarms for sustained heartbeat outages

4. **Dead TTS Keepalive Removal** (`deepgram_sagemaker_tts.py`)
   - Removed unused `_keepalive_task` and `_send_keepalive()` methods
   - Cleaned up misleading dead code

### Phase 2: Structured Log Context

1. **error_type Standardization** (5 files)
   - Added `error_type=type(e).__name__` to all exception logs
   - Replaced `exc_info=True` with structured error_type in bedrock_llm.py
   - Enables CloudWatch Insights aggregation by exception class

2. **TTS call_id Context** (`deepgram_sagemaker_tts.py`)
   - Verified structlog.contextvars propagation works for Pipecat tasks
   - Added explicit `call_id` to critical error log sites
   - All TTS logs now correlate to specific calls in multi-call containers

3. **Missing Structured Fields** (9 log sites)
   - Added required context fields to under-specified logs:
     - `tts_audio_receive_timeout`: call_id, timeout_seconds, endpoint_name
     - `tts_synthesis_error`: call_id, error_type, text_length
     - `tts_response_processor_error`: call_id, error_type, endpoint_name
     - `dynamodb_put_failed`: table_name, pk, sk
     - `dynamodb_update_failed`: table_name, pk, sk
     - `secrets_fetch_failed`: secret_arn, region
     - `session_end_failed`: error_type, end_status, turn_count

4. **call_id Standardization** (3 files)
   - Adopted `call_id` as canonical identifier across all components
   - Removed confusing `call_id=session_id` aliases
   - DynamoDB schema unchanged (no data migration)

5. **Dialin Event Parsing** (`pipeline_ecs.py`)
   - Replaced raw `data=str(data)[:200]` with structured SIP field parsing
   - Logs sip_call_id, sip_status_code, reason, from_uri, to_uri
   - Added safe fallback for malformed data

### Phase 3: Cleanup

1. **Log Level Corrections** (5 files)
   - `a2a_tool_call_timeout`: ERROR -> WARNING (expected operational event)
   - `audio_clipping_detected`: WARNING -> INFO (environmental condition)
   - `tts_close_message_failed`: WARNING -> DEBUG (expected on disconnect)
   - `tts_clear_message_failed`: WARNING -> DEBUG (expected on barge-in)
   - KB Lambda "Could not start ingestion": WARNING -> INFO (expected when empty)

2. **Bare Except Replacement** (`a2a/tool_adapter.py`)
   - Replaced 4 silent `except Exception: pass` blocks with `logger.debug()`
   - Metrics failures now visible in DEBUG logs

3. **RuntimeError Control Flow Removal** (`pipeline_ecs.py`)
   - Added `ConfigService.is_configured()` class method
   - Replaced 7 `except RuntimeError` blocks with explicit boolean checks
   - Eliminates risk of catching unrelated RuntimeError exceptions

4. **Import Cleanup** (`observability.py`)
   - Moved `import math` to module level (was inline in hot path)
   - Removed dead assignment in RMS calculation

### Bonus: ELB Health Check Log Suppression

- Disabled aiohttp access logs (`access_log=None` on `web.AppRunner`)
- Eliminated ~8,640 ELB health check log lines/day
- Log streams now contain only structured JSON events

## Files Modified

| File | Changes |
|------|---------|
| `app/task_protection.py` | Retry logic + consecutive failure tracking |
| `app/a2a/registry.py` | Grace period for empty discovery |
| `app/session_tracker.py` | Heartbeat escalation, log context |
| `app/services/deepgram_sagemaker_tts.py` | Dead code removal, context binding |
| `app/pipeline_ecs.py` | Dialin parsing, control flow cleanup |
| `app/a2a/tool_adapter.py` | Bare except replacement |
| `app/service_main.py` | Missing context fields |
| `app/secrets_loader.py` | Error context fields |
| `app/services/bedrock_llm.py` | error_type standardization |
| `app/observability.py` | Import cleanup, log levels |
| `app/services/config_service.py` | is_configured() method |

## Verification

- **Tests**: 437 passed, 2 pre-existing failures (unrelated)
- **Deploy**: Task definition v26→v27 successfully deployed
- **SIPp Test Calls**: Verified structured dialin events, heartbeat with task_id/active_count, task protection renewal, call_id on all events
- **Log Stream**: Zero access log entries, only structured JSON events

## Impact

- **Debugging**: Every error/warning log now includes sufficient context to identify affected call, component, and error class
- **Alerting**: Escalation logic enables CloudWatch alarms for task protection and heartbeat failures
- **Reliability**: Grace periods prevent transient failures from disrupting active calls
- **Performance**: Removed dead code and unnecessary imports
- **Cost**: Eliminated 8,640+ noise log lines/day

## Related Features

- [fix-observer-event-spam](./fix-observer-event-spam/) - Observer deduplication
- [fix-aws-crt-bidi-teardown-race](./fix-aws-crt-bidi-teardown-race/) - TTS/STT teardown fix
- [log-noise-cleanup](./log-noise-cleanup/) - Deprecation warning cleanup
