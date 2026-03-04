---
shipped: 2026-01-27
---

# Shipped: Quality Monitoring & Alerting

## Summary

Added proactive quality monitoring to the voice agent with audio quality metrics, CloudWatch alerting, session health tracking, and operational dashboard. This enables detection of issues before user complaints through real-time monitoring of latency, errors, resource usage, and audio quality.

## Key Changes

### CloudWatch Alerting (Phase 1)
- E2E Latency alarm: Avg > 2000ms for 3 consecutive 1-minute periods
- Error Rate alarm: > 5% failure rate over 5-minute window
- CPU Utilization alarm: > 80% sustained (2 of 3 periods)
- Memory Utilization alarm: > 85% sustained (2 of 3 periods)
- Optional SNS topic for alarm notifications

### Active Sessions Metric (Phase 2)
- `emit_session_health()` method in EMFLogger for real-time session tracking
- ActiveSessions metric emitted on call start/end
- ErrorCount by category for error visibility

### Audio Quality Observer (Phase 3)
- AudioQualityObserver class extending BaseObserver pattern
- RMS level (dBFS) and peak amplitude calculation per turn
- Silence duration tracking between utterances
- PoorAudioTurns metric (threshold: -55 dBFS)
- Fixed bug: Poor audio now counted once per turn, not per VAD event

### CloudWatch Dashboard (Phase 4)
- Service health summary with alarm status
- E2E latency percentiles (P50/P95/P99)
- Component latency breakdown (STT/LLM/TTS)
- Error rate timeline and completion status distribution
- CPU/Memory utilization graphs
- Conversation quality metrics (turns, interruptions)

### Container Restart Alarm (Phase 5)
- Detects container restarts via RunningTaskCount < 1
- Threshold: > 2 restarts per hour

### Documentation (Phase 6)
- CLAUDE.md updated with environment variables
- Alarm runbooks with thresholds and actions

## Testing

- 117 unit tests passing (78 for observability module)
- Manual verification via live test call
- Verified PoorAudioTurns=0 for normal phone audio (fix confirmed)
- Session health metrics emitting on call start/end
- All CloudWatch alarms created and dashboard functional

## Notes

- Audio quality monitoring enabled by default (`ENABLE_AUDIO_QUALITY_MONITORING=true`)
- Conversation logging disabled by default (`ENABLE_CONVERSATION_LOGGING=false`)
- Poor audio threshold set to -55 dBFS (typical phone audio is -40 to -50 dBFS)
- Dashboard URL: Output as `VoiceAgentEcs.DashboardUrl` in CloudFormation
