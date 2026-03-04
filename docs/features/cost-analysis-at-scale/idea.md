---
name: Cost Analysis at Scale
type: feature
priority: P2
effort: small
impact: medium
status: idea
created: 2026-02-24
related-to: ecs-auto-scaling
---

# Cost Analysis at Scale

## Problem Statement

The voice agent platform needs accurate cost projections as it scales from proof-of-concept (1-5 concurrent calls) to enterprise production (50-1000 concurrent calls). The previous cost estimates in the scaling analysis document referenced external cloud API pricing (Deepgram WebSocket, Cartesia HTTP) which no longer applies -- STT and TTS are now self-hosted on SageMaker.

Current cost drivers that need analysis:

- **SageMaker endpoints**: ml.g6.2xlarge (STT) and ml.g6.12xlarge (TTS) running 24/7
- **ECS Fargate compute**: Per-vCPU and per-GB-hour pricing across scaling range
- **NAT Gateway**: Data transfer for Daily.co WebRTC (SageMaker BiDi now routes via VPC endpoint)
- **Bedrock Claude**: Token-based pricing at various call volumes
- **Daily.co**: PSTN minutes and platform fees at enterprise scale
- **Supporting services**: DynamoDB (session tracking), CloudWatch (metrics/logs), Lambda (session counter), NLB

No formal cost model exists that maps call volume to infrastructure cost.

## Vision

A detailed cost model that:

1. **Maps call concurrency to monthly cost** at key thresholds (10, 50, 100, 500, 1000 concurrent calls)
2. **Breaks down cost by component** so we can identify and optimize the most expensive items
3. **Compares always-on vs auto-scaling costs** to quantify savings from auto-scaling
4. **Evaluates cost optimization strategies**: Reserved Instances, Savings Plans, SageMaker endpoint auto-scaling, right-sizing
5. **Projects SageMaker endpoint scaling needs** at each concurrency level (how many STT/TTS instances?)
6. **Includes Daily.co enterprise pricing** estimates for PSTN at scale

## Scope

### In Scope
- SageMaker endpoint costs (STT ml.g6.2xlarge, TTS ml.g6.12xlarge) at various instance counts
- ECS Fargate compute costs across the auto-scaling range
- NAT Gateway data transfer estimates (WebRTC only; SageMaker BiDi now routes via VPC endpoint)
- Bedrock Claude Haiku 4.5 token costs (estimated tokens per call)
- Daily.co PSTN per-minute and platform costs
- DynamoDB, CloudWatch, Lambda, NLB costs (fixed and variable components)
- Cost comparison: current state vs. optimized (Reserved Instances, Savings Plans)
- SageMaker endpoint auto-scaling cost savings vs. always-on

### Out of Scope
- Multi-region cost implications (separate analysis)
- Development/testing environment costs
- Personnel/operational costs

## Deliverables

1. **Cost model spreadsheet or document** with per-component breakdowns at 10, 50, 100, 500, 1000 call thresholds
2. **Recommendations** for cost optimization (which components to target first)
3. **Updated `docs/reference/scaling-analysis.md`** Section 4.7 with accurate cost projections

## Dependencies

- `ecs-auto-scaling` (planned) -- Determines min/max container counts and utilization patterns
- SageMaker endpoint load testing -- Determines how many STT/TTS instances needed per call volume
- Daily.co enterprise pricing -- Requires vendor conversation

## Research Required

- [ ] SageMaker ml.g6.2xlarge and ml.g6.12xlarge on-demand and reserved pricing (us-east-1)
- [ ] SageMaker endpoint auto-scaling pricing impact (scale-to-zero possible?)
- [ ] ECS Fargate Savings Plans pricing vs. on-demand
- [ ] NAT Gateway data transfer estimates for WebRTC (SageMaker BiDi no longer uses NAT -- routes via VPC endpoint)
- [ ] Bedrock Claude Haiku 4.5 token pricing and estimated tokens per average call
- [ ] Daily.co enterprise tier pricing for PSTN minutes
