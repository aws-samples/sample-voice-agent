---
id: noise-resistant-vad
name: Noise-Resistant VAD
type: Feature
priority: P1
effort: Medium
impact: High
created: 2026-02-24
related-to: observability-quality-monitoring, comprehensive-observability-metrics
---

# Noise-Resistant VAD

## Problem Statement

When testing the voice agent in noisy environments, the agent becomes inaudible because it is continuously being interrupted and unable to complete its responses. Background noise triggers false barge-in events, preventing the agent from speaking. This makes the system unusable in high background noise situations such as:

- Open office environments
- Public spaces (cafes, airports)
- Locations with HVAC or equipment noise
- Areas with traffic or street noise

## Proposed Solution

Improve voice activity detection (VAD) to better filter out background noise and prevent false interruptions. This may involve:

1. **VAD Parameter Tuning**: Adjust sensitivity thresholds to require stronger voice signals
2. **Noise Floor Detection**: Establish ambient noise baselines and only trigger on signals significantly above the floor
3. **Spectral Analysis**: Use frequency-based detection to distinguish speech from noise
4. **Minimum Duration Thresholds**: Require sustained audio to trigger barge-in (avoid brief noise spikes)
5. **Hysteresis**: Add delay before allowing new interruptions after agent starts speaking

## Success Criteria

- Agent can complete responses in environments with 60-70 dB background noise
- False barge-in rate reduced by 80% in noisy conditions
- No significant degradation in normal (quiet) environment performance
- Latency impact < 100ms

## Technical Considerations

- Current VAD implementation in Pipecat
- WebRTC VAD vs. Silero VAD options
- Configuration parameters available
- Testing across different noise profiles (white noise, babble, HVAC, traffic)
- Balance between responsiveness and noise immunity

## Related Components

- Barge-in detection system
- Audio input pipeline
- Conversation flow management
- STT/VAD integration

## Notes

- May need A/B testing to validate improvements
- Consider making noise resistance level configurable per deployment
- Document recommended settings for different environments
