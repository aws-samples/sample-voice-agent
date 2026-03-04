---
name: Route SageMaker BiDi Streaming Through VPC Endpoint
type: feature
priority: P1
effort: small
impact: high
status: shipped
created: 2026-02-24
shipped: 2026-02-24
related-to: cost-analysis-at-scale
---

# Route SageMaker BiDi Streaming Through VPC Endpoint

## Status: Shipped

Validated on 2026-02-24. Enabled `privateDnsEnabled: true` on the SageMaker Runtime VPC endpoint and confirmed BiDi streaming works for both STT and TTS through the VPC endpoint without NAT.

## What Changed

### Infrastructure

| File | Change |
|------|--------|
| `infrastructure/src/constructs/vpc-construct.ts` | `privateDnsEnabled` flipped from `false` to `true`, comment updated |

### Documentation

| File | Change |
|------|--------|
| `ARCHITECTURE.md` | VPC endpoint table and networking section updated; SageMaker Runtime now listed as supporting port 8443; removed "BiDi routes through NAT" language |
| `docs/reference/scaling-analysis.md` | Protocol table, Mermaid diagrams, security gap table, and VPC endpoint table updated to reflect VPC endpoint path |
| `docs/features/cost-analysis-at-scale/idea.md` | NAT cost driver updated to "WebRTC only" since SageMaker BiDi routes via VPC endpoint |
| `docs/features/deepgram-sagemaker-bidirectional-streaming/shipped.md` | Architecture diagram, key decisions table, and infra changes table updated |

### No Changes Required

- No application code changes -- DNS resolution change is transparent to the BiDi SDK
- Security group rules for port 8443 were already in place (both SageMaker SG and VPC endpoint SG)

## Validation Results

- Test call completed successfully with 2 turns, 0 errors
- STT: TTFB 0.254s, confidence 0.98 avg
- TTS: processing times 0.485s and 0.527s
- Both BiDi sessions opened and closed cleanly
- Call completion status: `completed`

## Background

All STT and TTS traffic previously routed through NAT gateways because we assumed VPC interface endpoints only support port 443. AWS confirmed (2026-02-24) that the SageMaker Runtime VPC endpoint does support BiDi streaming on port 8443.

### Previous path (through NAT)

```
ECS Task (private subnet)
  -> NAT Gateway (public subnet)
    -> runtime.sagemaker.<region>.amazonaws.com:8443
```

### Current path (through VPC endpoint)

```
ECS Task (private subnet)
  -> VPC Endpoint ENI (private subnet)
    -> SageMaker Runtime BiDi streaming
```

## Impact

- **Cost**: Eliminated NAT data processing charges ($0.045/GB) for all STT/TTS streaming audio
- **Latency**: Removed NAT hop from the real-time audio path
- **Security**: SageMaker traffic stays entirely within the VPC via PrivateLink
