---
id: observability-timing-metrics
name: Timing Metrics & CloudWatch EMF
type: Enhancement
priority: P1
effort: Medium
impact: High
created: 2026-01-26
---

# Timing Metrics & CloudWatch EMF

## Problem Statement

The voice agent has no visibility into performance metrics:

1. **No LLM timing** - We don't know how long Bedrock Claude takes to respond. Time to First Token (TTFT) and total response time are unmeasured.

2. **No end-to-end latency** - We can't measure the critical metric: time from when user stops speaking to when bot starts speaking. This directly impacts user experience.

3. **No CloudWatch metrics** - All data is in logs, requiring manual queries. There are no dashboards or alarms for performance monitoring.

## Why This Matters

- **User Experience**: Latency directly impacts conversation quality. Users perceive delays >500ms as awkward pauses.
- **Capacity Planning**: Without metrics, we can't identify bottlenecks or plan for scale.
- **Alerting**: Without CloudWatch metrics, we can't set up alarms for latency spikes.

## Proposed Solution

1. **LLM Timing**: Add timing around Bedrock calls to measure TTFT, total response time, and token count
2. **E2E Latency**: Measure VAD stop → first audio output latency
3. **CloudWatch EMF**: Emit metrics using Embedded Metric Format for automatic CloudWatch integration:
   - `STTLatency`, `LLMTimeToFirstByte`, `TTSTimeToFirstByte`
   - `E2ELatency`, `TokensUsed`, `CallDuration`

## Affected Areas

- backend/voice-agent/app/pipeline_ecs.py
- backend/voice-agent/app/observability.py (new file)
- infrastructure/src/stacks/ecs-stack.ts (optional dashboard)
