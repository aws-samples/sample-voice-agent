---
id: deepgram-sagemaker-bidirectional-streaming
status: planned
planned: 2026-02-18
---

# Deepgram SageMaker Bidirectional Streaming Migration — Implementation Plan

## Overview

Migrate STT and TTS from cloud APIs (Deepgram WebSocket, Cartesia HTTP) to SageMaker bidirectional streaming endpoints using Deepgram Marketplace model packages. This eliminates audio data leaving the VPC, removes API key dependencies for STT/TTS, and provides predictable infrastructure-based pricing via private offer `offer-cr2mh2ag35t7y`.

## Key Findings from Research

| Component | Available? | Source | Notes |
|-----------|-----------|--------|-------|
| STT (`DeepgramSageMakerSTTService`) | Built into Pipecat (v0.0.96+) | `pipecat.services.deepgram.stt_sagemaker` | Uses `SageMakerBidiClient` with `v1/listen` path |
| TTS (SageMaker) | **Not in Pipecat** | Must build custom | Deepgram Aura-2 TTS IS available on SageMaker Marketplace; Pipecat just lacks the wrapper |
| BiDi Client (`SageMakerBidiClient`) | Built into Pipecat (v0.0.96+) | `pipecat.services.aws.sagemaker.bidi_client` | Generic HTTP/2 streaming client for SageMaker endpoints |
| HTTP/2 SDK | pip extra | `pipecat-ai[sagemaker]` -> `aws_sdk_sagemaker_runtime_http2` | **Requires Python >= 3.12** |
| Deepgram STT on Marketplace | Yes | `Deepgram Voice AI- English Speech-to-Text (STT)` | Separate model package from TTS |
| Deepgram TTS on Marketplace | Yes | `Deepgram Voice AI- Aura-2 Text-to-Speech- English- Streaming` | Separate model package from STT |

### Deepgram TTS BiDi Protocol (confirmed from docs)

The Deepgram TTS WebSocket protocol at `v1/speak` uses:
- **Send text:** `{"type": "Speak", "text": "Your text here"}`
- **Flush audio:** `{"type": "Flush"}` — forces generation of buffered text
- **Clear buffer:** `{"type": "Clear"}` — clears internal text buffer (for interruptions)
- **Close connection:** `{"type": "Close"}`
- **Receive:** Binary audio chunks (linear16/mulaw/alaw at configured sample rate)
- **Query params on connect:** `model=aura-2-thalia-en&encoding=linear16&sample_rate=8000`

These map directly to `SageMakerBidiClient.send_json()` for control messages and binary receive for audio.

### Critical Constraints

| Constraint | Impact | Mitigation |
|-----------|--------|------------|
| **Python >= 3.12 required** | Current Dockerfile uses `python:3.11-slim` | Must upgrade base image; test all dependencies |
| Pipecat upgrade v0.0.100 -> v0.0.102 | `TTSService.run_tts()` now requires `context_id` parameter (breaking change) | Custom TTS service must implement new signature |
| No built-in TTS SageMaker service | Must build `DeepgramSageMakerTTSService` ourselves | Model after built-in STT service; use same `SageMakerBidiClient` |
| Factory disconnected from pipeline | `pipeline_ecs.py` hardcodes Deepgram/Cartesia; factory exists but is dead code | Wire factory into pipeline; add missing `PipelineConfig` fields |
| ECS task role has zero SageMaker permissions | Cannot invoke endpoints | Add IAM permissions in `ecs-stack.ts` |
| SageMaker SG only allows Lambda ingress | ECS tasks blocked from reaching SageMaker endpoints | Add ECS task SG as ingress source |
| Separate Marketplace subscriptions | STT and TTS are different model packages | Subscribe to both via the private offer |

## Implementation Phases

---

### Phase 1: Infrastructure Prerequisites

**Goal:** SageMaker endpoints deployable with real model package ARNs, correct IAM, networking, and Python 3.12.

#### Step 1.1: Accept Deepgram Private Offer (Manual, Blocking)

- [ ] Accept private offer `offer-cr2mh2ag35t7y` in AWS Marketplace (account `972801262139`, profile `voice-agent`)
- [ ] Subscribe to **both** model packages:
  - STT: `Deepgram Voice AI- English Speech-to-Text (STT)`
  - TTS: `Deepgram Voice AI- Aura-2 Text-to-Speech- English- Streaming`
- [ ] Record the model package ARNs from each subscription
- **Blocked:** Cannot deploy endpoints until offer is accepted

#### Step 1.2: Update CDK SageMaker Stack with Real ARNs

**File:** `infrastructure/src/stacks/sagemaker-stack.ts:52-60`

- [ ] Replace PLACEHOLDER ARNs with real model package ARNs from Marketplace
- [ ] Update CDK context defaults in `cdk.json` with the real ARNs
- [ ] Verify the production validation gate (lines 63-76) passes with real ARNs

#### Step 1.3: Add SageMaker IAM Permissions to ECS Task Role

**File:** `infrastructure/src/stacks/ecs-stack.ts`

The ECS task role currently has NO SageMaker permissions. Add:

- [ ] `sagemaker:InvokeEndpoint` — standard invocation fallback
- [ ] `sagemaker:InvokeEndpointWithResponseStream` — response streaming
- [ ] `sagemaker:InvokeEndpointWithBidirectionalStream` — HTTP/2 bidirectional streaming
- [ ] Scope permissions to the specific STT and TTS endpoint ARNs (from SSM)

#### Step 1.4: Add SageMaker Environment Variables to ECS Container

**File:** `infrastructure/src/stacks/ecs-stack.ts:317-331`

- [ ] Add `STT_PROVIDER` (default: `deepgram` for backward compatibility)
- [ ] Add `TTS_PROVIDER` (default: `cartesia` for backward compatibility)
- [ ] Add `STT_ENDPOINT_NAME` (from SSM `/voice-agent/sagemaker/stt-endpoint-name`)
- [ ] Add `TTS_ENDPOINT_NAME` (from SSM `/voice-agent/sagemaker/tts-endpoint-name`)

#### Step 1.5: Update VPC Networking for BiDi Streaming

**File:** `infrastructure/src/constructs/vpc-construct.ts`

- [ ] Add ECS task security group as ingress source on SageMaker security group (currently only Lambda SG allowed, line 104)
- [ ] Verify SageMaker Runtime VPC endpoint supports HTTP/2 on port 8443
- [ ] If VPC endpoint doesn't support port 8443, configure direct connectivity from ECS private subnets

#### Step 1.6: Upgrade Dockerfile to Python 3.12

**File:** `backend/voice-agent/Dockerfile`

- [ ] Change `FROM python:3.11-slim` to `FROM python:3.12-slim`
- [ ] Rebuild and test that all existing dependencies install cleanly on 3.12
- [ ] Verify PyTorch CPU, Silero VAD, and all other packages work on 3.12
- [ ] Run existing test suite to confirm no regressions

#### Step 1.7: Deploy and Validate SageMaker Endpoints

- [ ] Deploy SageMaker stack: `cdk deploy VoiceAgentSageMaker`
- [ ] Wait for both endpoints to reach `InService` status
- [ ] Test STT endpoint with sample audio via AWS CLI or Python script
- [ ] Test TTS endpoint with sample text via AWS CLI or Python script

---

### Phase 2: Backend — STT Migration

**Goal:** Replace Deepgram cloud STT with Pipecat's built-in `DeepgramSageMakerSTTService`.

#### Step 2.1: Upgrade Pipecat and Add Dependencies

**File:** `backend/voice-agent/requirements.txt`

- [ ] Upgrade `pipecat-ai` from `0.0.100` to `0.0.102` (or latest)
- [ ] Add `sagemaker` extra: `pipecat-ai[daily,silero,deepgram,cartesia,aws,sagemaker]==0.0.102`
- [ ] Verify `deepgram-sdk~=4.7.0` is resolved transitively (needed for `LiveOptions`)
- [ ] Address Pipecat v0.0.102 breaking changes:
  - `TTSService.run_tts()` now requires `context_id` parameter
  - `VADParams.stop_secs` default changed from 0.8 to 0.2
  - `TranscriptionUserTurnStopStrategy` renamed to `SpeechTimeoutUserTurnStopStrategy`
- [ ] Run tests to catch any breakage from the upgrade

#### Step 2.2: Update PipelineConfig and Service Main

**File:** `backend/voice-agent/app/pipeline_ecs.py:100-111`

The `PipelineConfig` dataclass is missing provider fields. The factory references `config.stt_endpoint` / `config.tts_endpoint` which don't exist.

- [ ] Add fields to `PipelineConfig`:
  ```python
  stt_provider: str = "deepgram"
  tts_provider: str = "cartesia"
  stt_endpoint: str = ""
  tts_endpoint: str = ""
  ```

**File:** `backend/voice-agent/app/service_main.py:243-251`

- [ ] Populate new fields from env vars:
  ```python
  stt_provider=os.environ.get("STT_PROVIDER", config.providers.stt_provider),
  tts_provider=os.environ.get("TTS_PROVIDER", config.providers.tts_provider),
  stt_endpoint=os.environ.get("STT_ENDPOINT_NAME", ""),
  tts_endpoint=os.environ.get("TTS_ENDPOINT_NAME", ""),
  ```

#### Step 2.3: Wire Factory into Pipeline for STT

**File:** `backend/voice-agent/app/pipeline_ecs.py:186-196`

Currently hardcodes `DeepgramSTTService`. Replace with factory:

- [ ] Update `factory.py:create_stt_service()` to add `sagemaker` provider:
  ```python
  from pipecat.services.deepgram.stt_sagemaker import DeepgramSageMakerSTTService
  from deepgram import LiveOptions

  stt = DeepgramSageMakerSTTService(
      endpoint_name=config.stt_endpoint,
      region=config.aws_region,
      live_options=LiveOptions(
          model="nova-3",
          language="en",
          interim_results=True,
          punctuate=True,
          encoding="linear16",
          sample_rate=8000,  # Match PSTN audio rate
          channels=1,
      ),
  )
  ```
- [ ] Replace hardcoded `DeepgramSTTService` in pipeline with `create_stt_service(config)` call
- [ ] Keep `"deepgram"` cloud provider as default/fallback

**Observability note:** The built-in `DeepgramSageMakerSTTService` passes `result=parsed` to `TranscriptionFrame` with the same Deepgram JSON structure (`channel.alternatives[0].confidence`). The `STTQualityObserver` should work without modification. Verify during integration testing.

#### Step 2.4: Remove Custom SageMaker STT Service

**File:** `backend/voice-agent/app/services/sagemaker_stt.py` (262 lines)

- [ ] Delete `sagemaker_stt.py` — replaced by Pipecat's built-in `DeepgramSageMakerSTTService`
- [ ] Update `services/__init__.py` to remove `SageMakerSTTService` from exports
- [ ] Verify no other files import from `sagemaker_stt` (grep)

---

### Phase 3: Backend — TTS Migration

**Goal:** Replace Cartesia cloud TTS with Deepgram Aura-2 TTS via SageMaker bidirectional streaming.

#### Step 3.1: Build `DeepgramSageMakerTTSService`

**New file:** `backend/voice-agent/app/services/deepgram_sagemaker_tts.py`

Pipecat does NOT have a built-in SageMaker TTS service. Build one using `SageMakerBidiClient`, modeling after the built-in STT service in `pipecat.services.deepgram.stt_sagemaker`:

- [ ] Create `DeepgramSageMakerTTSService(TTSService)` class
- [ ] Constructor params: `endpoint_name`, `region`, `voice` (default `aura-2-thalia-en`), `sample_rate`, `encoding`
- [ ] Use `SageMakerBidiClient` with:
  - `model_invocation_path="v1/speak"`
  - `model_query_string="model={voice}&encoding={encoding}&sample_rate={sample_rate}"`
- [ ] Implement `run_tts(text, context_id)` (new v0.0.102 signature):
  - Send `{"type": "Speak", "text": text}` via `send_json()`
  - Send `{"type": "Flush"}` via `send_json()` to trigger audio generation
  - Receive binary audio chunks from response stream
  - Yield `TTSAudioRawFrame` for each audio chunk (true streaming, not batch)
- [ ] Implement interruption handling:
  - On `TTSInterruptedFrame`, send `{"type": "Clear"}` to clear Deepgram's text buffer
- [ ] Connection lifecycle:
  - `start()`: Create `SageMakerBidiClient`, call `start_session()`, start response processor task
  - `stop()` / `cancel()`: Send `{"type": "Close"}`, cancel tasks, call `close_session()`
  - KeepAlive: Send `{"type": "KeepAlive"}` every 5s (match STT pattern)
- [ ] Implement `set_voice()` for runtime voice switching
- [ ] Match output sample rate to pipeline (8kHz for PSTN)

#### Step 3.2: Wire Factory into Pipeline for TTS

**File:** `backend/voice-agent/app/services/factory.py:69-116`

- [ ] Update `create_tts_service()` to support `TTS_PROVIDER=sagemaker`:
  ```python
  from .deepgram_sagemaker_tts import DeepgramSageMakerTTSService

  tts = DeepgramSageMakerTTSService(
      endpoint_name=config.tts_endpoint,
      region=config.aws_region,
      voice=config.voice_id,  # e.g., "aura-2-thalia-en"
      sample_rate=8000,
      encoding="linear16",
  )
  ```
- [ ] Replace hardcoded `CartesiaTTSService` in `pipeline_ecs.py:229-243` with `create_tts_service(config)` call
- [ ] Keep `"cartesia"` cloud provider as default/fallback

#### Step 3.3: Remove Custom SageMaker TTS Service

**File:** `backend/voice-agent/app/services/sagemaker_tts.py` (221 lines)

- [ ] Delete `sagemaker_tts.py` — replaced by `DeepgramSageMakerTTSService`
- [ ] Update `services/__init__.py` to remove `SageMakerTTSService` from exports
- [ ] Verify no other files import from `sagemaker_tts`

#### Step 3.4: Update Voice ID Configuration

- [ ] Update default `voice_id` in `config_service.py` for Deepgram Aura voices (e.g., `aura-2-thalia-en`)
- [ ] Add voice ID mapping in factory for backward compatibility: Cartesia UUID -> Deepgram Aura name
- [ ] Update `_map_voice_id_to_cartesia()` to become a general `_map_voice_id()` that handles both providers
- [ ] Available Deepgram Aura-2 voices (from `sagemaker_tts.py:DEEPGRAM_VOICES`):
  - `aura-2-thalia-en`, `aura-2-asteria-en`, `aura-2-luna-en`, `aura-2-athena-en`, `aura-2-arcas-en`, etc.

---

### Phase 4: Configuration & Switchover

**Goal:** Make the migration configurable with gradual rollout support.

#### Step 4.1: Wire Config Service into Pipeline

**File:** `backend/voice-agent/app/services/config_service.py`

The `ProviderConfig` already has `stt_provider` and `tts_provider` fields, and SSM parameters exist at `/voice-agent/config/stt-provider` and `/voice-agent/config/tts-provider`. But they're never wired into the pipeline.

- [ ] Ensure `AppConfig.providers` fields flow through to `PipelineConfig`
- [ ] Add `stt_endpoint_name` and `tts_endpoint_name` to `ProviderConfig` (from SSM)
- [ ] Add validation: if `stt_provider=sagemaker`, require `stt_endpoint_name` to be non-empty

#### Step 4.2: Make API Keys Optional

**Files:** `factory.py`, `infrastructure/src/constructs/secrets-construct.ts`

- [ ] Update factory to skip API key lookup when using SageMaker provider (don't require `DEEPGRAM_API_KEY` or `CARTESIA_API_KEY`)
- [ ] Make secrets conditional in CDK — only required when using cloud providers
- [ ] Update health check to validate SageMaker connectivity when using SageMaker provider

#### Step 4.3: Pipeline Startup Logging

- [ ] Log which STT/TTS provider is active at pipeline startup
- [ ] Log SageMaker endpoint names when using SageMaker provider
- [ ] Add provider info to session tracking metadata in DynamoDB

---

### Phase 5: Testing & Validation

#### Step 5.1: Unit Tests

- [ ] Add `test_deepgram_sagemaker_tts.py` — mock `SageMakerBidiClient`, verify:
  - Correct `v1/speak` path and query string
  - `Speak`, `Flush`, `Clear`, `Close` JSON messages sent correctly
  - Audio binary chunks converted to `TTSAudioRawFrame`
  - `run_tts(text, context_id)` signature (v0.0.102 breaking change)
- [ ] Add `test_factory.py` — test `create_stt_service()` and `create_tts_service()` for all providers
- [ ] Update `test_service_main.py` for new `PipelineConfig` fields
- [ ] Update `test_observability.py` for SageMaker provider error categorization

#### Step 5.2: Integration Testing

- [ ] Deploy SageMaker endpoints in dev environment
- [ ] Switch `STT_PROVIDER=sagemaker` and verify transcription accuracy with interim results
- [ ] Switch `TTS_PROVIDER=sagemaker` and verify audio quality and latency
- [ ] Run end-to-end call and measure E2E latency (target: < 2000ms)
- [ ] Verify TTS time-to-first-byte (target: < 500ms)
- [ ] Test barge-in: verify `Clear` message interrupts TTS correctly
- [ ] Test with 8kHz PSTN audio — confirm Deepgram handles it without resampling

#### Step 5.3: Observability Validation

- [ ] Confirm `STTLatency`, `STTConfidence`, `STTWordCount` metrics emit (should work — SageMaker STT passes `result=parsed`)
- [ ] Confirm `TTSTimeToFirstByte`, `TTSAudioDuration` metrics emit
- [ ] Confirm `E2ELatency` metric reflects SageMaker path
- [ ] Verify SageMaker endpoint CloudWatch alarms (P95 latency, error rate) fire correctly
- [ ] Check CloudWatch dashboard shows SageMaker metrics

#### Step 5.4: Fallback Testing

- [ ] `STT_PROVIDER=deepgram` — confirm cloud API still works
- [ ] `TTS_PROVIDER=cartesia` — confirm cloud API still works
- [ ] SageMaker endpoint unavailable — verify graceful error handling (not auto-fallback)

#### Step 5.5: Load Testing

- [ ] Run concurrent calls to verify SageMaker endpoint auto-scaling
- [ ] Monitor for BiDi connection leaks (each call = one session)
- [ ] Verify 30-minute session limit isn't hit for long calls

---

## Dependency Graph

```
Phase 1 (Infra)
  ├── 1.1 Accept Marketplace offer (manual, blocking)
  ├── 1.2 Update CDK ARNs (depends on 1.1)
  ├── 1.3 Add IAM permissions (independent)
  ├── 1.4 Add env vars to ECS (independent)
  ├── 1.5 Update VPC networking (independent)
  ├── 1.6 Upgrade Python 3.12 (independent, HIGH PRIORITY)
  └── 1.7 Deploy & validate endpoints (depends on 1.1-1.5)

Phase 2 (STT) — can start 2.1-2.2 immediately; 2.3+ depends on 1.7
  ├── 2.1 Upgrade pipecat + deps (depends on 1.6 for Python 3.12)
  ├── 2.2 Update PipelineConfig + service_main (independent)
  ├── 2.3 Wire factory for STT (depends on 2.1, 2.2)
  └── 2.4 Remove custom SageMaker STT (depends on 2.3)

Phase 3 (TTS) — can parallel with Phase 2
  ├── 3.1 Build DeepgramSageMakerTTSService (depends on 2.1 for deps)
  ├── 3.2 Wire factory for TTS (depends on 3.1, 2.2)
  ├── 3.3 Remove custom SageMaker TTS (depends on 3.2)
  └── 3.4 Update voice ID config (depends on 3.2)

Phase 4 (Config) — depends on Phase 2, Phase 3
  ├── 4.1 Wire config service
  ├── 4.2 Make API keys optional
  └── 4.3 Pipeline startup logging

Phase 5 (Testing) — depends on all above
  ├── 5.1 Unit tests (can start during Phase 2-3)
  ├── 5.2 Integration testing (depends on 1.7)
  ├── 5.3 Observability validation
  ├── 5.4 Fallback testing
  └── 5.5 Load testing
```

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Python 3.12 upgrade breaks dependencies** | Medium | High | Test PyTorch, Silero VAD, all pip packages on 3.12 first; rollback plan |
| Pipecat v0.0.102 breaking changes cause regressions | Medium | Medium | Run full test suite after upgrade; address `run_tts(context_id)`, `VADParams.stop_secs` changes |
| SageMaker endpoint not ready (offer not accepted) | Low | High | Keep cloud API as default; SageMaker is opt-in via env var |
| Custom TTS service has higher latency than Cartesia | Medium | Medium | Benchmark TTFB; optimize chunk streaming; Deepgram claims sub-second latency |
| VPC endpoint doesn't support HTTP/2 port 8443 | Medium | Medium | Test in dev first; may need direct connectivity |
| Sample rate mismatch (8kHz PSTN vs SageMaker) | Low | Low | Deepgram supports `sample_rate` param on connect; configure 8000 |
| BiDi connection leak under load | Low | Medium | Ensure `close_session()` on every pipeline stop/cancel; add connection count monitoring |

## Estimated Effort

| Phase | Effort | Duration | Can Start |
|-------|--------|----------|-----------|
| Phase 1: Infrastructure | Medium | 1-2 days | Immediately (1.1 is manual) |
| Phase 2: STT Migration | Small | 1 day | After Python 3.12 upgrade |
| Phase 3: TTS Migration | Large | 2-3 days | Parallel with Phase 2 |
| Phase 4: Configuration | Small | 0.5 day | After Phases 2-3 |
| Phase 5: Testing | Medium | 2-3 days | Unit tests during Phases 2-3 |
| **Total** | **Large** | **~7-10 days** | |

## Files Modified

| File | Change Type | Phase |
|------|-------------|-------|
| `backend/voice-agent/Dockerfile` | **Change Python 3.11 -> 3.12** | 1.6 |
| `backend/voice-agent/requirements.txt` | Upgrade pipecat, add sagemaker extra | 2.1 |
| `infrastructure/src/stacks/sagemaker-stack.ts` | Replace placeholder ARNs | 1.2 |
| `infrastructure/src/stacks/ecs-stack.ts` | Add IAM perms, env vars | 1.3, 1.4 |
| `infrastructure/src/constructs/vpc-construct.ts` | Add ECS SG ingress to SageMaker SG | 1.5 |
| `backend/voice-agent/app/pipeline_ecs.py` | Add PipelineConfig fields, wire factory | 2.2, 2.3, 3.2 |
| `backend/voice-agent/app/service_main.py` | Populate new PipelineConfig fields | 2.2 |
| `backend/voice-agent/app/services/factory.py` | Update STT/TTS creation for SageMaker | 2.3, 3.2 |
| `backend/voice-agent/app/services/config_service.py` | Wire provider config into pipeline | 4.1 |
| `backend/voice-agent/app/services/sagemaker_stt.py` | **Delete** | 2.4 |
| `backend/voice-agent/app/services/sagemaker_tts.py` | **Delete** | 3.3 |
| `backend/voice-agent/app/services/__init__.py` | Update exports | 2.4, 3.3 |
| `backend/voice-agent/app/services/deepgram_sagemaker_tts.py` | **New** — custom TTS service | 3.1 |
| `backend/voice-agent/tests/test_deepgram_sagemaker_tts.py` | **New** — TTS unit tests | 5.1 |
| `backend/voice-agent/tests/test_factory.py` | **New** — factory unit tests | 5.1 |

## References

- Pipecat `DeepgramSageMakerSTTService` source: `pipecat.services.deepgram.stt_sagemaker`
- Pipecat `SageMakerBidiClient` source: `pipecat.services.aws.sagemaker.bidi_client`
- Deepgram TTS WebSocket docs: https://developers.deepgram.com/docs/tts-websocket
- Deepgram STT streaming docs: https://developers.deepgram.com/docs/stt/getting-started
- Deepgram SageMaker announcement: https://deepgram.com/learn/deepgram-brings-real-time-speech-intelligence-to-amazon-sagemaker
- AWS Marketplace STT: https://aws.amazon.com/marketplace/pp/prodview-bootgv4bvrrwi
- AWS Marketplace TTS: https://aws.amazon.com/marketplace/pp/prodview-mkw35rzmnmwoa
- Pipecat TTS docs: https://docs.pipecat.ai/server/services/tts/deepgram
- Pipecat STT docs: https://docs.pipecat.ai/server/services/stt/deepgram
- Reference demo: https://github.com/deepgram/rxconnect-deepgram-pipecat-sagemaker-demo
- Pipecat AWS workshop: https://github.com/pipecat-ai/aws-deepgram-workshop
