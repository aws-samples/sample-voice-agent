---
id: cdk-deprecation-cleanup-v3
name: CDK Deprecation Cleanup V3
type: Tech Debt
priority: P1
effort: Small
impact: Medium
shipped: 2026-02-20
---

# CDK Deprecation Cleanup V3 - Shipped

## Summary

Final round of CDK deprecation cleanup. All known deprecation warnings have been eliminated.

## What Was Fixed

| Deprecated API | Replacement | File |
|----------------|-------------|------|
| `QueryStringProps#stats` | `statsStatements` | `voice-agent-monitoring-construct.ts` |
| `TableOptions#pointInTimeRecovery` | `pointInTimeRecoverySpecification` | `crm-stack.ts` (3 tables) |

## History

- **V1** (shipped 2026-01-27): Fixed `containerInsights` and `logRetention`
- **V2** (shipped 2026-02-02): Fixed KB custom resource provider's `logRetention`
- **V3** (this): Fixed `stats` -> `statsStatements` and `pointInTimeRecovery` -> `pointInTimeRecoverySpecification`
