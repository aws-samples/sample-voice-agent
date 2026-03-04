---
shipped: 2026-01-26
---

# Shipped: Timing Metrics & CloudWatch EMF

## Summary

Added comprehensive timing metrics to the voice pipeline with CloudWatch EMF (Embedded Metric Format) integration. The system now captures end-to-end latency, turn timing, and call-level summaries, emitting them as structured logs that CloudWatch automatically extracts as metrics.

## Key Changes

- **MetricsCollector class**: Accumulates per-turn and per-call metrics with async timing context managers
- **MetricsObserver**: Non-blocking pipeline observer that captures VAD and TTS events for E2E latency measurement
- **CloudWatch EMF output**: Turn metrics and call summaries emitted in EMF format for automatic metric extraction
- **Turn tracking**: Automatic turn boundary detection via UserStartedSpeakingFrame and TTSStartedFrame events

## Metrics Captured

| Metric | Unit | Description |
|--------|------|-------------|
| E2ELatency | Milliseconds | VAD stop to first audio output |
| STTLatency | Milliseconds | Audio complete to transcription |
| LLMTimeToFirstByte | Milliseconds | Request to first LLM token |
| LLMTotalResponseTime | Milliseconds | Full LLM response time |
| TTSTimeToFirstByte | Milliseconds | Text to first audio chunk |
| CallDuration | Seconds | Total call time |
| TurnCount | Count | Conversation turns per call |

## Files Changed

- `backend/voice-agent/app/observability.py` - New: Core metrics module (650+ lines)
- `backend/voice-agent/app/pipeline_ecs.py` - Modified: MetricsObserver integration
- `backend/voice-agent/app/service_main.py` - Modified: MetricsCollector lifecycle
- `backend/voice-agent/tests/test_observability_metrics.py` - New: 35 unit tests

## Testing

- **Unit tests**: 35 tests covering all components (TurnMetrics, CallMetrics, EMFLogger, TimingContext, MetricsCollector)
- **Integration verified**: Deployed to ECS, made test call, confirmed E2E latency captured (809ms)
- **EMF format validated**: CloudWatch Logs receiving properly formatted metrics
- **Security review**: PASS (no Critical/High issues)
- **QA validation**: APPROVED (100% test coverage, all edge cases handled)

## Technical Decisions

- Used pipecat's **observer pattern** (not pipeline processor) for non-blocking metrics collection
- **perf_counter()** for timing precision (nanosecond resolution, monotonic)
- **Conditional metric emission** - only metrics with values are included in EMF logs
- **Two-tier dimensions**: Environment (primary), CallId (secondary) to balance observability vs CloudWatch costs

## Notes

- CloudWatch dashboard creation is optional and can be added separately
- The observer pattern fix was critical - the original processor approach blocked audio
- Future enhancement: Add per-service latency breakdown and token usage metrics
