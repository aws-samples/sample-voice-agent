---
id: deepgram-sagemaker-bidirectional-streaming
status: shipped
shipped: 2026-02-19
---

# Deepgram SageMaker Bidirectional Streaming Migration — Shipped

## Summary

Migrated STT and TTS from cloud APIs (Deepgram WebSocket, Cartesia HTTP) to SageMaker bidirectional streaming endpoints using Deepgram Marketplace model packages. All audio now stays within the VPC via HTTP/2 bidirectional streaming on port 8443. Multi-turn conversation with tool calling (including Knowledge Base RAG) is fully operational.

## What Changed

### Architecture: Before vs After

```
BEFORE (Cloud API Mode):
  Caller -> Daily -> ECS -> Deepgram Cloud (STT, WebSocket, internet)
                         -> Cartesia Cloud (TTS, HTTP, internet)
                         -> Bedrock (LLM, VPC endpoint)

AFTER (SageMaker Mode):
  Caller -> Daily -> ECS -> SageMaker STT Endpoint (BiDi HTTP/2, port 8443, via VPC endpoint)
                         -> SageMaker TTS Endpoint (BiDi HTTP/2, port 8443, via VPC endpoint)
                         -> Bedrock (LLM, VPC endpoint)

  * Traffic routes via VPC endpoint (privateDnsEnabled: true). Both standard invoke
    (port 443) and BiDi streaming (port 8443) are supported by the sagemaker.runtime
    VPC interface endpoint. No NAT gateway required for SageMaker traffic.
```

### Key Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| Use Pipecat's built-in `DeepgramSageMakerSTTService` for STT | No custom code needed; handles BiDi protocol natively |
| Build custom `DeepgramSageMakerTTSService` for TTS | Pipecat has no built-in SageMaker TTS service; we wrote ~320 lines using `SageMakerBidiClient` with Deepgram's `v1/speak` WebSocket protocol |
| Monkey-patch `SageMakerBidiClient` credentials | Built-in client hardcodes `EnvironmentCredentialsResolver` which fails on ECS Fargate; patch adds `ContainerCredentialsResolver` to the chain |
| Enable `privateDnsEnabled` on sagemaker.runtime VPC endpoint | BiDi streaming (port 8443) is supported by the VPC endpoint. With private DNS enabled, hostname resolves to VPC endpoint ENI, keeping all SageMaker traffic off NAT |
| Remove TTS KeepAlive messages | Deepgram TTS SageMaker shim only supports `Speak`, `Flush`, `Clear`, `Close`. Sending `KeepAlive` caused `"unknown variant KeepAlive"` error |
| Pass `tools_list` to `OpenAILLMContext` | Tools were registered with `register_function()` but NOT passed to the context, so Bedrock Converse API never received `toolConfig` — LLM couldn't call tools |
| Backward compatible defaults | Cloud APIs remain the default; SageMaker requires explicit `STT_PROVIDER=sagemaker` / `TTS_PROVIDER=sagemaker` env vars |

### Infrastructure Changes

| File | Change |
|------|--------|
| `infrastructure/.env` | `USE_CLOUD_APIS=false`, real Deepgram Marketplace model ARNs |
| `infrastructure/src/stacks/sagemaker-stack.ts` | SSM params at stack level (matching stub stack logical IDs), real model package ARNs |
| `infrastructure/src/stacks/ecs-stack.ts` | SageMaker IAM permissions (`InvokeEndpoint`, `InvokeEndpointWithResponseStream`, `InvokeEndpointWithBidirectionalStream`), SG rules (ports 443+8443), `STT_PROVIDER`/`TTS_PROVIDER`/`STT_ENDPOINT_NAME`/`TTS_ENDPOINT_NAME` env vars |
| `infrastructure/src/constructs/vpc-construct.ts` | `privateDnsEnabled: true` on sagemaker.runtime VPC endpoint (supports BiDi on port 8443) |
| `infrastructure/src/constructs/sagemaker-endpoint-construct.ts` | Removed SSM params (moved to stack level) |

### Backend Changes

| File | Change |
|------|--------|
| `app/services/deepgram_sagemaker_tts.py` | **New** ~320-line custom TTS service using `SageMakerBidiClient` with Deepgram `v1/speak` protocol |
| `app/services/sagemaker_credentials.py` | **New** monkey-patch for ECS Fargate credential chain (`ContainerCredentialsResolver`) |
| `app/services/factory.py` | Rewritten with SageMaker provider support, credential patch calls |
| `app/pipeline_ecs.py` | Factory calls for STT/TTS, new `PipelineConfig` fields, tools passed to `OpenAILLMContext` |
| `app/service_main.py` | New env var/SSM config population for provider and endpoint fields |
| `Dockerfile` | Python 3.11 -> 3.12 (required for `aws_sdk_sagemaker_runtime_http2`) |
| `requirements.txt` | `pipecat-ai` 0.0.100 -> 0.0.102 with `sagemaker` extra |
| `app/services/sagemaker_stt.py` | **Deleted** (replaced by Pipecat built-in) |
| `app/services/sagemaker_tts.py` | **Deleted** (replaced by new custom service) |

### Directory Rename

`backend/pipecat/` was renamed to `backend/voice-agent/` to fix a Python namespace collision with the `pipecat-ai` package. ~50 files updated for the rename.

## Issues Debugged & Resolved

| # | Issue | Root Cause | Fix |
|---|-------|-----------|------|
| 1 | CDK diff showed "no differences" | `USE_CLOUD_APIS=true` in `.env` caused stub stack deployment | Set to `false` |
| 2 | SSM parameter CloudFormation conflict | Logical IDs changed when params moved into construct | Moved SSM params back to stack level |
| 3 | Zero quota for GPU instances | Account had no SageMaker endpoint quota for ml.g6 | Requested & approved quota increases |
| 4 | No audio on call - BiDi session hung silently | VPC endpoint private DNS hijacked `runtime.sagemaker.us-east-1.amazonaws.com:8443`, routing to VPC endpoint that only handles port 443 | Initially disabled `privateDnsEnabled`; later confirmed VPC endpoint does support port 8443 and re-enabled it (see `sagemaker-bidi-vpc-endpoint` feature) |
| 5 | BiDi `start_session()` hung silently | `EnvironmentCredentialsResolver` fails on ECS Fargate (no `AWS_ACCESS_KEY_ID` env var); error swallowed by HTTP/2 stack | Created `sagemaker_credentials.py` monkey-patch with `ContainerCredentialsResolver` |
| 6 | TTS connection died after first greeting | `KeepAlive` message rejected by Deepgram TTS shim (`"unknown variant KeepAlive"`) | Removed keepalive task from TTS service |
| 7 | Tools not working (LLM never called tools) | `tools_list` built by `_register_tools()` but not passed to `OpenAILLMContext`; Bedrock Converse API received no `toolConfig` | Pass `tools_list` to context: `tools=tools_list if tools_list else NOT_GIVEN` |

## Performance Characteristics

From production call `1dc200c0` (4 turns, 101 seconds):

| Metric | Value |
|--------|-------|
| STT BiDi connect time | ~140ms |
| TTS BiDi connect time | ~100ms |
| LLM TTFB (Bedrock Claude 3.5 Haiku) | ~900ms-1.1s |
| Tool execution (KB search) | 416ms |
| Avg agent response latency | 2581ms |
| TTS tokens/second | 35-61 |

## SageMaker Endpoints

| Endpoint | Instance Type | Model |
|----------|--------------|-------|
| `voice-agent-poc-poc-stt-endpoint` | ml.g6.2xlarge (1x L4 GPU) | Deepgram Nova-3 STT |
| `voice-agent-poc-poc-tts-endpoint` | ml.g6.12xlarge (4x L4 GPU) | Deepgram Aura-2 TTS |

Marketplace agreements:
- STT: `agmt-4g0x0vro7ff1gyoxsk0el5teg` (product `prod-iwvzul7dwjo5m`)
- TTS: `agmt-79pxfexy86il5povg5v3q51fd` (product `prod-fw6tkkdwldvku`)

## Known Issues

- **STT metrics all null/zero**: `stt_final_count: 0`, `stt_confidence_avg: null` across all turns despite transcripts reaching LLM correctly. Tracked in `docs/features/fix-stt-metrics-sagemaker/idea.md` (P1 bug).
- **Shutdown `InvalidStateError`**: Benign `concurrent.futures._base.InvalidStateError` during BiDi session close — the HTTP/2 stream is already cancelled when the `on_complete` callback fires. Does not affect functionality.

## Validation

Verified end-to-end on call `1dc200c0-1bb3-4609-b7d4-46eea448c9dc`:
- Bot greets caller
- Caller asks for FAQ information
- LLM calls `search_knowledge_base` tool (3 results, top score 0.637)
- Bot reads back return policy from knowledge base
- Caller says thanks, hangs up
- Clean shutdown of both BiDi sessions
