---
name: Log Analysis
type: tech-debt
priority: P1
effort: medium
impact: high
status: idea
created: 2026-02-26
related-to: fix-observer-event-spam, observability-quality-monitoring
depends-on: []
---

# Log Analysis

## Problem Statement

A codebase-wide audit of warning/error log sites identified **real bugs masked by noisy logs**, **missing context that makes logs useless for debugging**, and **inconsistent conventions** that undermine the value of our structured logging investment. The problem is not just log volume -- it is that our logs are not telling us what we need to know, and in several cases they are hiding genuine design flaws.

## Real Issues Surfaced

### 1. Task Protection Renewal Has No Retry Logic

**File:** `app/task_protection.py:127-162`

`set_protected()` retries 3 times with backoff. `renew_if_protected()` makes a single attempt -- no retries. A transient network failure during renewal starts a silent 30-minute countdown to protection lapse (the protection TTL is 30 minutes, renewed every 30 seconds). When protection lapses, ECS auto-scaling can terminate the task mid-conversation.

The `task_protection_all_retries_exhausted` alarm (per AGENTS.md) only fires for `set_protected()` failures, not for renewal failures. There is no alarm path for renewal lapse.

**Impact:** Active calls can be killed mid-conversation during scale-in events.

### 2. A2A Registry Drops Agents on Transient Failures

**File:** `app/a2a/registry.py:refresh()`

The `refresh()` method builds a fresh `new_agent_cache` each cycle. Two problems:

- If a previously-healthy agent's card endpoint is temporarily unreachable, the agent is dropped from the routing table immediately. No grace period, no carry-forward of the cached entry.
- If CloudMap returns zero endpoints (transient API issue), the entire routing table is cleared on a single empty response. All remote tools vanish from the LLM context.

**Impact:** Transient network issues cause tools to disappear from conversations.

### 3. Heartbeat Failure Does Not Escalate

**File:** `app/session_tracker.py:334-341`

The heartbeat loop logs `heartbeat_failed` at WARNING on every failure but has no consecutive failure counter and no escalation. If heartbeat fails for >5 minutes (the TTL), the session counter Lambda considers the task dead. Auto-scaling becomes blind to this task's sessions, potentially scaling down and terminating it.

**Impact:** Auto-scaling makes incorrect decisions based on stale data.

### 4. Session End Failure Leaves Stale "Active" Records

**File:** `app/service_main.py:374-379`

When `end_session()` fails, the DynamoDB record remains in "active" status until TTL expires (24 hours via `TTL_ACTIVE_SESSION`). The session counter Lambda overcounts active sessions, potentially triggering unnecessary scale-out.

**Impact:** Wasted infrastructure cost from phantom sessions.

### 5. TTS Service Has No Call Correlation

**File:** `app/services/deepgram_sagemaker_tts.py`

`DeepgramSageMakerTTSService` does not receive or bind any `call_id` or `session_id`. In a multi-call container, all TTS logs (`tts_synthesis_error`, `tts_audio_receive_timeout`, `tts_response_processor_error`) are impossible to correlate to a specific call. The `tts_audio_receive_timeout` at line 205 has zero context fields.

**Impact:** TTS errors in production cannot be attributed to the affected call.

### 6. Dead Keepalive Code in TTS

**File:** `app/services/deepgram_sagemaker_tts.py:105, 291-292, 309-317`

`_keepalive_task` is initialized as `None`, referenced in `_disconnect()` cleanup, but never assigned. `_send_keepalive()` is defined but never called. A code comment explains the Deepgram SageMaker shim does not support KeepAlive messages. This dead code is misleading and suggests a past connection stability issue that was never properly resolved or cleaned up.

### 7. Exception Flow Used for Config Access Control

**File:** `app/pipeline_ecs.py:62-102, 591`

Six property accessors catch `RuntimeError` from `ConfigService._get_config()` as a control flow mechanism, returning default values when the config is not loaded. This is used to support the `ecs_main.py` code path where `ConfigService` is never initialized. Using exceptions for control flow is a design smell -- an explicit `ConfigService.is_configured()` check would be clearer and avoid the risk of catching unrelated `RuntimeError` exceptions.

## Logging Standardization Issues

### Missing Structured Context

Many error/warning logs lack the fields needed to be actionable:

| Log Event | File | Missing Fields |
|-----------|------|----------------|
| `tts_audio_receive_timeout` | `deepgram_sagemaker_tts.py:205` | Everything -- zero context fields |
| `tts_synthesis_error` | `deepgram_sagemaker_tts.py:226` | `call_id`, `error_type`, `text_preview` |
| `tts_response_processor_error` | `deepgram_sagemaker_tts.py:390` | `call_id`, `error_type`, `endpoint_name` |
| `heartbeat_failed` | `session_tracker.py:340` | `task_id`, `active_count`, `consecutive_failures` |
| `dynamodb_put_failed` | `session_tracker.py:384` | `table_name`, item PK/SK |
| `dynamodb_update_failed` | `session_tracker.py:431` | `table_name`, item PK/SK |
| `dialin_warning` / `dialin_error` | `pipeline_ecs.py:522,526` | Raw `data=str(data)[:200]` instead of parsed fields like `sip_code`, `reason` |
| `secrets_fetch_failed` | `secrets_loader.py:63` | `secret_arn`, `region` |
| `session_end_failed` | `service_main.py:375` | `call_id`, `end_status`, `turn_count` |

### Missing `error_type` on Error Logs

Most error logs include `error=str(e)` but not `error_type=type(e).__name__`. Without the exception class, you cannot aggregate errors by type in CloudWatch Insights or build alarms on specific exception classes. This should be a standard convention: every `logger.error()` and `logger.warning()` that catches an exception must include both fields.

### `call_id` vs `session_id` Confusion

Some logs use `session_id` only (session_tracker.py), some use `call_id` only (observability.py), some use both (service_main.py). In `pipeline_ecs.py:671`, `call_id=session_id` -- they are the same value but named differently. This causes confusion when correlating across components and should be standardized to a single canonical identifier.

### Log Level Inconsistencies

| Event | Current | Should Be | Reasoning |
|-------|---------|-----------|-----------|
| `a2a_tool_call_timeout` | ERROR | WARNING | Timeouts are expected operational events, same concept as `tool_execution_timeout` which is WARNING |
| `heartbeat_failed` (after 5+ consecutive) | WARNING | ERROR | Persistent failure blinds auto-scaling -- deserves an alarm |
| `task_protection_renewal_failed` (after 3+ consecutive) | WARNING | ERROR | Protection lapse can kill calls |
| `audio_clipping_detected` | WARNING | INFO or metric-only | Audio environment condition, not an application error |
| `tts_close_message_failed` | WARNING | DEBUG | Expected during abrupt disconnects |
| `tts_clear_message_failed` | WARNING | DEBUG | Expected during barge-in disconnects |
| `Could not start ingestion` (KB Lambda) | WARNING | INFO | Explicitly expected when S3 bucket is empty |

### Silent Error Swallowing

Four sites use bare `except Exception: pass` with no logging at all:

1. `service_main.py:393` -- Transport cleanup on shutdown
2. `service_main.py:561` -- A2A registry stop on shutdown
3. `a2a/tool_adapter.py:115,157,180,220` -- Metrics recording failures (4 sites)

The shutdown cases (1-2) are acceptable. The metrics cases (3) should at minimum log at DEBUG so a broken metrics pipeline can be diagnosed.

### Convention Violations

All Lambda functions under `infrastructure/src/functions/` use stdlib `logging` with f-string formatting, violating the structlog convention documented in AGENTS.md. These are separate runtime contexts (Lambda vs ECS) but the inconsistency makes cross-component log analysis harder.

## Proposed Approach

### Phase 1: Fix Real Bugs

1. **Add retry logic to `renew_if_protected()`** -- 2-3 attempts with backoff, matching `set_protected()`. Add consecutive failure counter. Escalate to ERROR after 3+ failures to trigger alarms.
2. **Add grace period to A2A registry** -- Carry forward cached agent entries when card fetch fails transiently. Require 2-3 consecutive empty CloudMap responses before clearing the routing table.
3. **Add escalation to heartbeat loop** -- Track consecutive failures. After 5+ (2.5 min), escalate to `logger.error("heartbeat_persistent_failure")` to trigger alarms.
4. **Remove dead TTS keepalive code** -- Delete `_keepalive_task`, `_send_keepalive()`, and related cleanup.

### Phase 2: Standardize Log Context

1. **Establish mandatory fields for error/warning logs:**
   - `error_type=type(e).__name__` on every exception log
   - `call_id` on every per-call log (including TTS -- bind via constructor or `structlog.contextvars`)
   - `component` prefix on event names (e.g., `tts_synthesis_error`, `a2a_tool_call_timeout` -- already partially done)
2. **Add missing context fields** to the 9 under-specified log sites listed above.
3. **Standardize `call_id`/`session_id`** to a single canonical name across all components.
4. **Parse structured data in dialin events** instead of logging raw `data=str(data)[:200]`.

### Phase 3: Correct Log Levels

1. **Downgrade expected conditions** to INFO/DEBUG (clipping, TTS close/clear failures, KB ingestion).
2. **Add escalation logic** for periodic failures (heartbeat, task protection, A2A polling) -- WARNING on first failure, ERROR after N consecutive.
3. **Align timeout log levels** -- `a2a_tool_call_timeout` and `tool_execution_timeout` should use the same level.
4. **Replace bare `except Exception: pass`** with `logger.debug()` in metrics recording paths.
5. **Replace `except RuntimeError` control flow** in `pipeline_ecs.py` with explicit `ConfigService.is_configured()` check.

## Files to Modify

| File | Changes |
|------|---------|
| `app/task_protection.py` | Add retry logic + consecutive failure tracking to `renew_if_protected()` |
| `app/a2a/registry.py` | Carry forward cached agents on transient failures, require consecutive empty responses |
| `app/session_tracker.py` | Add consecutive failure counter + escalation, add missing log context |
| `app/services/deepgram_sagemaker_tts.py` | Remove dead keepalive code, add call context binding, add missing log fields |
| `app/pipeline_ecs.py` | Replace `except RuntimeError` control flow, parse dialin event data |
| `app/observability.py` | Correct log levels for audio clipping, move `import math` to module level |
| `app/a2a/tool_adapter.py` | Replace bare `except: pass` with `logger.debug()` |
| `app/service_main.py` | Add missing context to `session_end_failed` |
| `app/services/bedrock_llm.py` | Add `error_type` to error logs |
| `app/tools/executor.py` | Add `error_type` standardization |
| `app/secrets_loader.py` | Add `secret_arn`, `region` to error logs |

## Success Criteria

- Task protection renewal retries on transient failure (no silent lapse)
- A2A tools survive transient CloudMap/agent outages (grace period)
- Heartbeat failures escalate to alarms after sustained outage
- Every warning/error log includes enough context to identify the affected call, component, and error class
- Consistent `call_id` naming across all components
- Log levels accurately reflect severity (expected conditions at INFO/DEBUG, genuinely concerning conditions at WARNING/ERROR)

## Estimated Effort

Medium -- 3-4 days. Phase 1 (real bugs) is the priority and touches 4 files with focused changes. Phases 2-3 are systematic but mechanical -- adding context fields and adjusting log levels across ~10 files.
