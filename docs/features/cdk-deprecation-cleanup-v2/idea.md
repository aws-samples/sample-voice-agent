---
id: cdk-deprecation-cleanup-v2
name: CDK Deprecation Cleanup V2
type: Tech Debt
priority: P1
effort: Small
impact: Medium
created: 2026-01-28
---

# CDK Deprecation Cleanup V2

## Problem Statement

Despite the previous CDK deprecation cleanup effort, new deprecation warnings have emerged during deployment:

1. **`aws-cdk-lib.aws_lambda.FunctionOptions#logRetention`** - Deprecated, should use `logGroup` instead. This API will be removed in the next major CDK release.

2. **`url.parse()` Node.js deprecation** - Still persisting with security implications (CVEs not issued for vulnerabilities). The WHATWG URL API should be used instead.

These warnings indicate remaining technical debt that needs to be addressed before the next CDK major version release.

## Why It Matters

- **Future compatibility**: Deprecated APIs will be removed in next major CDK release
- **Security**: The `url.parse()` deprecation has known security implications
- **Clean deployments**: Warnings obscure meaningful output during deployments
- **Dependency updates**: May need to update or replace packages using deprecated APIs

## Affected Areas

- Lambda function configurations using `logRetention` property
- Any code or dependencies using `url.parse()`
- Potentially external packages that need replacement

## Notes

- Previous cleanup addressed `containerInsights` deprecation
- This round focuses on Lambda log retention and url.parse()
- May require finding alternative packages if deprecation is in external dependencies
