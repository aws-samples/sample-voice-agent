---
id: deepgram-sagemaker-bidirectional-streaming
name: Deepgram SageMaker Bidirectional Streaming Migration
type: Feature
priority: P0
effort: Large
impact: High
created: 2026-02-18
---

# Deepgram SageMaker Bidirectional Streaming Migration

## Problem Statement

The voice agent currently uses the Deepgram cloud API for STT (`pipecat.services.deepgram.stt.DeepgramSTTService`) via WebSocket, and Cartesia cloud API for TTS. This means:

1. **Audio data leaves the VPC** -- every audio frame is sent to Deepgram's cloud endpoints over the public internet, creating data residency and compliance concerns.
2. **API key dependency** -- the `DEEPGRAM_API_KEY` stored in Secrets Manager is a shared secret that must be rotated and protected; a leak exposes the account.
3. **No VPC-level network isolation** -- the ECS tasks require outbound internet access to reach Deepgram/Cartesia APIs, broadening the network attack surface.
4. **Cost structure** -- cloud API pricing is per-minute; a SageMaker endpoint with a private offer (offer ID: `offer-cr2mh2ag35t7y`) provides predictable infrastructure-based pricing.
5. **Latency** -- an extra network hop to external APIs adds variable latency vs. invoking a SageMaker endpoint within the same VPC.

We have a **Deepgram private offer** (`offer-cr2mh2ag35t7y`) that provides access to Deepgram models on AWS Marketplace for deployment as SageMaker endpoints. Deepgram and AWS have collaborated on a new **SageMaker Bidirectional Streaming API** (`InvokeEndpointWithBidirectionalStream`) that enables real-time, HTTP/2-based streaming STT and TTS within the VPC.

## Proposed Solution

Migrate both STT and TTS from cloud APIs to SageMaker bidirectional streaming endpoints using the Deepgram Marketplace model packages.

### Phase 1: Marketplace Subscription & Endpoint Deployment

1. **Accept the private offer** `offer-cr2mh2ag35t7y` in AWS Marketplace (account `972801262139`).
2. **Subscribe to model packages** -- obtain the STT (Nova-3) and TTS (Aura) model package ARNs from the Marketplace subscription.
3. **Update CDK infrastructure** (`infrastructure/src/stacks/sagemaker-stack.ts` and `infrastructure/src/constructs/sagemaker-endpoint-construct.ts`) with the real model package ARNs replacing the current PLACEHOLDER values.
4. **Deploy SageMaker endpoints** with appropriate instance types:
   - STT: `ml.g6.2xlarge` (1x L4 GPU) -- already configured
   - TTS: `ml.g6.12xlarge` (4x L4 GPU) -- already configured
5. **Validate endpoint health** -- confirm endpoints reach `InService` status and respond to test invocations.

### Phase 2: STT Migration (Deepgram Cloud API -> SageMaker BiDi Streaming)

**Current state:** `pipeline_ecs.py:192` uses `DeepgramSTTService` (cloud WebSocket API).

**Target state:** Use Pipecat's built-in `DeepgramSageMakerSTTService` from `pipecat.services.deepgram.stt_sagemaker`.

Key changes:
- **`backend/voice-agent/app/services/factory.py`** -- Update `create_stt_service()` to use `DeepgramSageMakerSTTService` when `STT_PROVIDER=sagemaker`:
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
- **`backend/voice-agent/app/pipeline_ecs.py`** -- Update the default pipeline to use the factory's `create_stt_service()` instead of directly instantiating `DeepgramSTTService`.
- **Remove custom `sagemaker_stt.py`** -- the current `backend/voice-agent/app/services/sagemaker_stt.py` uses synchronous `invoke_endpoint` with audio buffering (batch, not streaming). This should be replaced entirely by Pipecat's native `DeepgramSageMakerSTTService` which uses HTTP/2 bidirectional streaming.
- **Dependencies** -- add `deepgram-sdk` and `aws-sdk-sagemaker-runtime-http2` (or equivalent Python package) to `requirements.txt`.

### Phase 3: TTS Migration (Cartesia Cloud API -> SageMaker BiDi Streaming)

**Current state:** `factory.py:82` uses `CartesiaTTSService` (cloud API) by default.

**Target state:** Use Deepgram Aura TTS via SageMaker bidirectional streaming.

Key changes:
- Investigate whether Pipecat has a built-in `DeepgramSageMakerTTSService` (check latest pipecat releases).
- If not available, build a TTS service using the Deepgram SDK's SageMaker transport for TTS streaming.
- Update `create_tts_service()` factory to support `TTS_PROVIDER=sagemaker` with bidirectional streaming.
- Update voice ID mappings -- switch from Cartesia voice IDs to Deepgram Aura voice names (e.g., `aura-2-thalia-en`, `aura-2-asteria-en`).

### Phase 4: Infrastructure & Configuration Updates

- **Environment variables** -- switch defaults: `STT_PROVIDER=sagemaker`, `TTS_PROVIDER=sagemaker`.
- **Secrets Manager** -- `DEEPGRAM_API_KEY` becomes optional (only needed for cloud API fallback).
- **VPC endpoints** -- confirm SageMaker Runtime VPC endpoint (`infrastructure/src/constructs/vpc-construct.ts:134`) supports bidirectional streaming on port 8443.
- **IAM permissions** -- ECS task role needs `sagemaker:InvokeEndpointWithBidirectionalStream` in addition to existing `sagemaker:InvokeEndpoint`.
- **Security groups** -- verify SageMaker endpoint SG allows inbound from ECS tasks on required ports.
- **CloudWatch alarms** -- existing SageMaker alarms in `sagemaker-endpoint-construct.ts` should cover the new streaming endpoints.

### Phase 5: Testing & Validation

- Verify STT produces accurate transcriptions with interim results via SageMaker.
- Verify TTS generates audio with acceptable latency (target: < 500ms TTFB).
- Run end-to-end voice agent call and validate E2E latency metrics.
- Confirm observability metrics (`STTLatency`, `STTConfidence`, etc.) still report correctly.
- Load test to verify SageMaker endpoint auto-scaling behavior.
- Validate fallback path: if SageMaker endpoint is unavailable, can we fall back to cloud API?

## Affected Areas

- `backend/voice-agent/app/services/factory.py` -- STT/TTS service creation
- `backend/voice-agent/app/services/sagemaker_stt.py` -- remove/replace with Pipecat built-in
- `backend/voice-agent/app/services/sagemaker_tts.py` -- remove/replace
- `backend/voice-agent/app/pipeline_ecs.py` -- pipeline STT instantiation
- `backend/voice-agent/requirements.txt` -- new dependencies
- `infrastructure/src/stacks/sagemaker-stack.ts` -- model package ARNs
- `infrastructure/src/constructs/sagemaker-endpoint-construct.ts` -- endpoint config
- `infrastructure/src/constructs/vpc-construct.ts` -- VPC endpoint for HTTP/2 streaming
- `infrastructure/src/stacks/ecs-stack.ts` -- IAM permissions, environment variables
- `infrastructure/src/constructs/secrets-construct.ts` -- DEEPGRAM_API_KEY becomes optional
- `backend/voice-agent/app/observability.py` -- STT quality observer compatibility
- `backend/voice-agent/tests/` -- update tests for new service classes

## Dependencies

- Deepgram private offer `offer-cr2mh2ag35t7y` must be accepted in account `972801262139`
- SageMaker endpoints must be deployed and InService before switching providers
- Pipecat framework must include `DeepgramSageMakerSTTService` (verify minimum pipecat version)
- AWS SDK HTTP/2 client for bidirectional streaming support
- Reference implementation: [deepgram/rxconnect-deepgram-pipecat-sagemaker-demo](https://github.com/deepgram/rxconnect-deepgram-pipecat-sagemaker-demo)

## Notes

- The Deepgram SageMaker BiDirectional Streaming API uses HTTP/2 on port 8443 -- different from standard SageMaker `invoke_endpoint` on port 443. VPC endpoint configuration may need updating.
- Pipecat's `DeepgramSageMakerSTTService` handles the HTTP/2 bidirectional streaming protocol natively -- no custom WebSocket implementation needed.
- The existing custom `SageMakerSTTService` in `services/sagemaker_stt.py` uses synchronous `invoke_endpoint` with 500ms audio batching -- this is fundamentally different from true bidirectional streaming and should be replaced.
- Consider keeping cloud API as a fallback (`STT_PROVIDER=deepgram`) for development/testing environments that don't have SageMaker endpoints deployed.
- The private offer may have specific instance type requirements or usage commitments -- review offer terms before deployment.
- SageMaker bidirectional streaming supports up to 30 minutes per connection -- well within typical call durations.
- Audio format compatibility: PSTN audio is 8kHz; verify SageMaker endpoint handles 8kHz input or if we need to upsample to 16kHz.
