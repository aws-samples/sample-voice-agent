---
id: stt-tts-latency-benchmarking
name: STT/TTS Latency Benchmarking
type: Feature
priority: P1
effort: Medium
impact: High
created: 2026-02-18
---

# STT/TTS Latency Benchmarking

## Problem Statement

The voice agent currently supports both SageMaker-hosted and API-driven STT/TTS providers, but there is no systematic way to measure and compare their performance characteristics. Key unknowns include:

1. **No latency comparison data** - We don't have quantitative measurements of how SageMaker-hosted STT/TTS latency compares to API-driven alternatives (e.g., Deepgram API vs SageMaker Deepgram). Cold start, warm request, and sustained throughput latencies are all unmeasured.

2. **No quality comparison** - Beyond latency, there may be differences in transcription accuracy (WER), audio quality, and streaming behavior between the two deployment models that affect end-to-end user experience.

3. **No reproducible test process** - Ad-hoc testing makes it difficult to track improvements over time or evaluate new provider configurations. We need a repeatable benchmarking process.

## Why This Matters

- **Architecture Decisions**: The choice between SageMaker-hosted and API-driven STT/TTS has cost, latency, and operational complexity tradeoffs. Without data, these decisions are based on assumptions.
- **E2E Latency Budget**: STT and TTS are major contributors to the overall E2E latency. Understanding their individual contributions is critical for optimization.
- **Cost Optimization**: SageMaker endpoints have fixed costs (instance hours) while API-driven services charge per request. Latency data combined with cost analysis informs the optimal deployment strategy at different traffic levels.

## Proposed Solution

1. **Test Harness**: Build a benchmarking framework that can run standardized audio samples through both SageMaker and API-driven STT/TTS pipelines, capturing per-request timing metrics (time to first byte, total latency, processing time).

2. **Metrics Collection**: Capture and store benchmark results including:
   - STT: Time to first partial transcript, time to final transcript, word error rate
   - TTS: Time to first audio chunk, total synthesis time, audio quality metrics
   - Infrastructure: Cold start latency, p50/p95/p99 latency distributions

3. **Comparison Report**: Generate side-by-side comparison reports that highlight latency differences, identify bottlenecks, and provide actionable recommendations.

4. **CI Integration** (stretch): Optionally run benchmarks as part of the deployment pipeline to catch performance regressions.

## Affected Areas

- backend/voice-agent/app/services/stt/ (SageMaker and API STT implementations)
- backend/voice-agent/app/services/tts/ (SageMaker and API TTS implementations)
- backend/voice-agent/tests/ (new benchmark test suite)
- docs/ (benchmark results and analysis)
