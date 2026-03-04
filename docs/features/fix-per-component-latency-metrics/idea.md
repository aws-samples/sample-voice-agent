---
name: Fix Per-Component Latency Metrics
type: bug
priority: P2
effort: medium
impact: high
status: idea
created: 2026-02-23
related-to: observability-timing-metrics, observability-quality-monitoring
depends-on: []
---

# Fix Per-Component Latency Metrics

## Problem Statement

The `turn_completed` event reports `null` for all per-component latency breakdowns:

```json
{
  "event": "turn_completed",
  "stt_latency_ms": null,
  "llm_ttfb_ms": null,
  "tts_ttfb_ms": null
}
```

The `call_metrics_summary` also shows `0.0` for all averages:

```json
{
  "event": "call_metrics_summary",
  "avg_stt_ms": 0.0,
  "avg_llm_ms": 0.0,
  "avg_tts_ms": 0.0,
  "avg_agent_response_ms": 4842.5
}
```

Only the aggregate `AvgAgentResponseLatency` (E2E from user speech end to first bot audio) is captured at 4,842ms. We have no visibility into where that time is spent across STT, LLM, and TTS components.

Observed during a live call on 2026-02-23. Pipecat's built-in metrics DO fire (e.g., `AWSBedrockLLMService#2 TTFB: 1.17s`, `DeepgramSageMakerTTSService#2 processing time: 0.37s`), but these values are not being captured into the turn metrics collector.

## Impact

- **No latency breakdown**: Cannot identify which component (STT, LLM, TTS) is the bottleneck
- **Dashboard gaps**: CloudWatch dashboard shows E2E latency but can't drill down
- **Capacity planning**: Cannot make informed decisions about which component to optimize
- **Alarm gaps**: Cannot set per-component latency alarms (e.g., "alert if LLM TTFB > 2s")

## Root Cause Hypothesis

The metrics collector likely relies on pipecat's `MetricsFrame` or specific frame types (`TTFBMetricsFrame`, `ProcessingMetricsFrame`) to extract per-component timings. The SageMaker STT/TTS services and/or the metrics observer may not be emitting these frames in the expected format, or the turn tracker may not be correlating them to the active turn.

Pipecat's debug logs show the TTFB and processing times ARE being calculated internally:
- `AWSBedrockLLMService#2 TTFB: 1.1706s`
- `DeepgramSageMakerTTSService#2 processing time: 0.373s`

But these are not flowing into the `MetricsCollector`'s per-turn tracking.

## Proposed Investigation

1. Check `app/observers/metrics_observer.py` -- how does it capture TTFB/processing metrics from pipecat?
2. Check `app/services/metrics_collector.py` -- how are per-component latencies associated with turns?
3. Check pipecat's `MetricsFrame` types -- what frames do `AWSBedrockLLMService` and `DeepgramSageMakerSTTService`/`DeepgramSageMakerTTSService` emit?
4. Verify that the metrics observer is registered in the right position in the pipeline to receive these frames

## Files to Investigate

- `backend/voice-agent/app/observers/metrics_observer.py`
- `backend/voice-agent/app/services/metrics_collector.py`
- `backend/voice-agent/app/observers/` -- all observer files
- `backend/voice-agent/app/pipeline_ecs.py` -- observer registration and pipeline assembly

## Estimated Effort

Medium -- ~3-4 hours. Need to trace the metrics frame flow through the pipeline and fix the collection/correlation logic.
