---
started: 2026-01-26
---

# Implementation Plan: Timing Metrics and CloudWatch EMF

## Overview

Add comprehensive timing metrics to the voice pipeline with CloudWatch EMF integration. Metrics are emitted as structured JSON to stdout, where CloudWatch Logs automatically extracts them as CloudWatch Metrics.

**Related Documents**:
- [System Design](./system-design.md) - Architecture, data flow, CloudWatch integration
- [Implementation Blueprint](./implementation-blueprint.md) - Detailed code specifications

## Implementation Steps

- [x] Step 1: Create observability.py module
  - Create `/backend/voice-agent/app/observability.py`
  - Implement `TurnMetrics` and `CallMetrics` dataclasses
  - Implement `EMFLogger` for CloudWatch EMF formatting
  - Implement `MetricsCollector` class
  - Implement timing context managers

- [x] Step 2: Add unit tests
  - Create `/backend/voice-agent/tests/test_observability_metrics.py`
  - Test TurnMetrics and CallMetrics aggregation
  - Test EMF log format validation
  - Test MetricsCollector lifecycle
  - Test async timing context managers

- [x] Step 3: Integrate with service_main.py
  - Import observability module
  - Create MetricsCollector in `_run_pipeline()`
  - Pass collector to `create_voice_pipeline()`
  - Call `finalize()` on completion/error

- [x] Step 4: Integrate with pipeline_ecs.py
  - Accept optional MetricsCollector parameter
  - Add turn tracking via event handlers
  - Wire up VAD events for turn boundaries
  - Add timing hooks for E2E latency

- [ ] Step 5: Validate in CloudWatch
  - Deploy to staging environment
  - Verify EMF logs appear in CloudWatch Logs
  - Verify metrics extracted to CloudWatch Metrics
  - Test CloudWatch Logs Insights queries

- [ ] Step 6: Create CloudWatch dashboard (optional)
  - P50/P90/P99 latency graphs
  - Call duration distribution
  - Error rate by category
  - Turn count histogram

## Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| EMF implementation | Custom JSON (no library) | Minimal dependencies, full control |
| Timer precision | `time.perf_counter()` | Highest resolution, not affected by clock adjustments |
| Dimension strategy | Environment (primary), CallId (secondary) | Balance observability vs cost |
| Turn detection | VAD events | Already available in pipecat transport |

## Metrics Specification

| Metric | Unit | Measurement Point |
|--------|------|-------------------|
| STTLatency | Milliseconds | Audio complete to transcription |
| LLMTimeToFirstByte | Milliseconds | Request sent to first token |
| LLMTotalResponseTime | Milliseconds | Request sent to response complete |
| TTSTimeToFirstByte | Milliseconds | Text input to first audio chunk |
| E2ELatency | Milliseconds | VAD stop to first audio output |
| CallDuration | Seconds | Total call time |
| TurnCount | Count | Conversation turns per call |

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `backend/voice-agent/app/observability.py` | Create | Core observability module |
| `backend/voice-agent/tests/test_observability_metrics.py` | Create | Unit tests |
| `backend/voice-agent/app/service_main.py` | Modify | Create/finalize collector |
| `backend/voice-agent/app/pipeline_ecs.py` | Modify | Turn tracking, timing hooks |

## Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| EMF format rejected | Low | Medium | Validate against AWS spec in tests |
| CallId dimension costs | Medium | Medium | Use only as secondary dimension |
| Timing overhead | Low | Low | perf_counter is nanosecond resolution |
| Missing turn boundaries | Medium | Low | Default emit on call end |

## CloudWatch Queries (for validation)

**Turn Latency Distribution**:
```sql
filter event = "turn_metrics"
| stats avg(E2ELatency) as avg, pct(E2ELatency, 90) as p90 by bin(5m)
```

**Call Summary Analysis**:
```sql
filter event = "call_summary"
| stats count() as calls, avg(TurnCount) as avg_turns, avg(CallDuration) as avg_duration
  by CompletionStatus
```

## Success Criteria

1. EMF logs appear in CloudWatch Logs with correct format
2. Metrics auto-extracted to `VoiceAgent/Pipeline` namespace
3. P90 latency values visible in CloudWatch Metrics
4. No measurable impact on call latency (<1ms overhead)
5. All tests pass
