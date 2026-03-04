---
id: sagemaker-bidi-vpc-endpoint
name: Route SageMaker BiDi Streaming Through VPC Endpoint
type: feature
priority: P1
effort: small
impact: high
status: shipped
shipped: 2026-02-24
---

# Route SageMaker BiDi Streaming Through VPC Endpoint - Shipped

## Summary

Enabled private DNS on the SageMaker Runtime VPC endpoint to route all STT/TTS BiDi streaming traffic through PrivateLink instead of NAT gateways. This eliminates NAT data processing charges and keeps SageMaker traffic entirely within the VPC.

## What Was Delivered

### Infrastructure Change

- **File**: `infrastructure/src/constructs/vpc-construct.ts`
- **Change**: Flipped `privateDnsEnabled` from `false` to `true` on SageMaker Runtime VPC endpoint
- **Impact**: BiDi streaming on port 8443 now routes through VPC endpoint

### Documentation Updates

- **ARCHITECTURE.md**: Updated VPC endpoint table and networking section
- **docs/reference/scaling-analysis.md**: Updated protocol tables and Mermaid diagrams
- **docs/features/cost-analysis-at-scale/idea.md**: Updated NAT cost driver to "WebRTC only"
- **docs/features/deepgram-sagemaker-bidirectional-streaming/shipped.md**: Updated architecture documentation

### No Application Code Changes Required

- DNS resolution change is transparent to the BiDi SDK
- Security group rules for port 8443 already in place

## Validation

- Test call completed successfully with 2 conversation turns
- STT: TTFB 0.254s, confidence 0.98 avg
- TTS: processing times 0.485s and 0.527s
- Both BiDi sessions opened and closed cleanly
- Call completion status: `completed`

## Traffic Path Change

### Before (through NAT)
```
ECS Task (private subnet)
  -> NAT Gateway (public subnet)
    -> runtime.sagemaker.<region>.amazonaws.com:8443
```

### After (through VPC Endpoint)
```
ECS Task (private subnet)
  -> VPC Endpoint ENI (private subnet)
    -> SageMaker Runtime BiDi streaming
```

## Impact

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| **Cost** | $0.045/GB NAT data processing | $0/GB (VPC endpoint) | Eliminated NAT charges for STT/TTS |
| **Latency** | Extra NAT hop | Direct VPC endpoint | Removed network hop |
| **Security** | Traffic exits VPC | Stays within VPC via PrivateLink | Enhanced security posture |

## Background

Previously assumed VPC interface endpoints only support port 443. AWS confirmed (2026-02-24) that SageMaker Runtime VPC endpoint supports BiDi streaming on port 8443 with private DNS enabled.

## Related Features

- [cost-analysis-at-scale](./cost-analysis-at-scale/) - Cost optimization analysis
- [deepgram-sagemaker-bidirectional-streaming](./deepgram-sagemaker-bidirectional-streaming/) - BiDi streaming implementation
