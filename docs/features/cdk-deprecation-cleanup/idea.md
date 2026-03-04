---
id: cdk-deprecation-cleanup
name: CDK Deprecation Cleanup
type: Tech Debt
priority: P1
effort: Medium
impact: Medium
created: 2026-01-26
---

# CDK Deprecation Cleanup

## Problem Statement

The CDK infrastructure code uses deprecated APIs that generate warnings during deployment:

1. **`aws_ecs.ClusterProps#containerInsights`** - Deprecated in favor of `containerInsightsV2`
2. **`url.parse()` Node.js deprecation** - Using legacy URL parsing that has security implications (CVEs not issued for vulnerabilities)

These warnings indicate technical debt that could break in future CDK or Node.js versions. The deprecation warnings clutter deployment output and mask potentially important messages.

## Why It Matters

- **Future compatibility**: Deprecated APIs may be removed in next major CDK release
- **Security**: The `url.parse()` deprecation has security implications
- **Clean deployments**: Warnings obscure meaningful output during deployments
- **Best practices**: Staying current with AWS CDK patterns

## Affected Areas

- infrastructure/src/stacks/ecs-stack.ts (containerInsights)
- infrastructure/src/constructs/ (any ECS-related constructs)
- Any CDK code using url.parse() patterns
