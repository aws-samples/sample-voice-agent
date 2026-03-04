---
id: cdk-test-cleanup
name: Fix Pre-existing CDK Test Failures
type: Tech Debt
priority: P2
effort: Small
impact: Medium
shipped: 2026-02-20
---

# CDK Test Cleanup - Shipped

## Summary

Fixed all three pre-existing CDK test failures and restructured the monolithic test file into focused test modules.

## What Was Fixed

1. **PrivateDnsEnabled assertion**: Updated to correctly expect `false` for the SageMaker Runtime endpoint
2. **Security group naming**: Updated regex to match `'Voice Agent ECS Service'` instead of the old `'Pipecat ECS Service'`
3. **KB_KNOWLEDGE_BASE_ID**: Test now correctly asserts that the env var is NOT injected (read from SSM at runtime instead)

## Structural Improvement

The monolithic `stacks.test.ts` was split into focused test files:
- `ecs.test.ts`
- `network-storage.test.ts`
- `capability-agents.test.ts`
- `crm.test.ts`
- `sagemaker-botrunner.test.ts`
- `config.test.ts`
