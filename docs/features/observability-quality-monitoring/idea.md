---
id: observability-quality-monitoring
name: Quality Monitoring & Alerting
type: Enhancement
priority: P2
effort: Medium
impact: Medium
created: 2026-01-26
---

# Quality Monitoring & Alerting

## Problem Statement

The voice agent lacks proactive quality monitoring:

1. **No audio quality metrics** - We don't track audio levels (RMS, peak), silence duration, or VAD confidence. Poor audio quality causes STT failures that are hard to diagnose.

2. **No alerting** - Issues are discovered reactively through user complaints. There's no automated alerting for latency spikes, error rates, or service degradation.

3. **No health visibility** - Beyond basic health checks, there's no visibility into container health, memory usage, or concurrent call capacity.

## Why This Matters

- **Proactive Operations**: With alerting, we can detect and respond to issues before users report them
- **Root Cause Analysis**: Audio quality metrics help distinguish "user's audio was bad" from "our STT failed"
- **Capacity Management**: Understanding concurrent call behavior helps with scaling decisions

## Proposed Solution

1. **Audio Quality Metrics**:
   - Audio levels (RMS, peak) to detect silence or clipping
   - Silence duration between utterances
   - VAD confidence scores

2. **CloudWatch Alerting**:
   - High latency alerts (>2s E2E)
   - Error rate alerts (>5% failure)
   - Container restart alerts (>2/hour)

3. **Health Dashboard**:
   - Active sessions count
   - Memory/CPU utilization
   - Error rate by category

## Affected Areas

- backend/voice-agent/app/pipeline_ecs.py
- backend/voice-agent/app/audio_monitor.py (new file)
- infrastructure/src/stacks/ecs-stack.ts (CloudWatch alarms)
