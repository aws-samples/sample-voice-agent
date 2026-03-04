---
id: comprehensive-observability-metrics
name: Comprehensive Observability Metrics
type: Enhancement
priority: P1
effort: Medium
impact: High
created: 2026-02-06
---

# Comprehensive Observability Metrics

## Problem Statement

Our current observability system has several gaps that limit our ability to effectively monitor and improve voice agent quality:

1. **Misleading "E2E Latency" Metric**: What we call "end-to-end latency" only measures the agent's internal processing time (VAD stop to TTS start). It doesn't capture the full user experience including network transit, VAD detection delays, or audio playback buffering.

2. **Missing Quality Signals**: We track audio RMS/peak levels but lack other critical quality indicators:
   - STT confidence scores from Deepgram (we log them but don't aggregate)
   - LLM token counts and generation rates
   - Network/WebRTC metrics (RTT, jitter, packet loss)
   - Conversation flow patterns (gaps, overlaps, abandoned turns)

3. **No Composite Quality Score**: There's no single metric to quickly assess call quality. Operators must manually correlate multiple metrics to identify problematic calls.

4. **Limited Conversation Flow Visibility**: We track turn count and interruptions but don't analyze:
   - Turn-taking smoothness (delays between speakers)
   - Abandoned turns (user speaks but no bot response)
   - Repeated utterances (possible STT failure indicator)
   - Speaking time ratios (user vs bot engagement)

## Why This Matters

- **Debugging**: Current "E2E" metric doesn't explain why users experience delays. Is it network? VAD? LLM? We can't tell.
- **Quality Assessment**: Without confidence scores and flow metrics, we can't identify calls with poor STT accuracy or awkward conversation patterns.
- **Operational Efficiency**: A composite quality score would enable automatic flagging of problematic calls for review.
- **User Experience**: Understanding true end-to-end latency helps identify network bottlenecks affecting real users.

## Proposed Solution

Expand observability to capture:

1. **Rename and Expand Latency Metrics**:
   - Rename current "E2E" to "AgentResponseLatency" (accurate description)
   - Add component-level breakdowns with better precision
   - Track VAD detection delay separately

2. **STT Quality Metrics**:
   - Aggregate Deepgram confidence scores per turn
   - Track interim vs final transcription ratios
   - Log confidence trends over the course of a call

3. **LLM Quality Metrics**:
   - Input/output token counts per response
   - Tokens per second (generation speed)
   - Track prompt caching efficiency

4. **Network/WebRTC Metrics** (via Daily transport):
   - Round-trip time (RTT)
   - Jitter and packet loss
   - Audio bitrate

5. **Conversation Flow Metrics**:
   - Gap duration between speakers
   - Abandoned turn detection
   - Speaking time ratios
   - Response latency (bot stop to user start)

6. **Composite Quality Score**:
   - Weighted combination of: confidence, latency, audio quality, flow smoothness
   - Enables quick identification of low-quality calls

## Affected Areas

- `backend/voice-agent/app/observability.py` - New metrics and observers
- `backend/voice-agent/app/pipeline_ecs.py` - Additional frame observers
- `infrastructure/src/constructs/voice-agent-monitoring-construct.ts` - New CloudWatch metrics and alarms
- CloudWatch Dashboard - Additional widgets for new metrics

## Success Criteria

- [ ] AgentResponseLatency metric renamed and tracked
- [ ] STT confidence scores aggregated and emitted
- [ ] LLM token counts captured per response
- [ ] At least 3 WebRTC metrics (RTT, jitter, packet loss) tracked
- [ ] Conversation flow metrics (gaps, abandoned turns) implemented
- [ ] Composite quality score calculated and emitted
- [ ] CloudWatch dashboard updated with new visualizations
- [ ] Documentation updated with new metric definitions
