---
id: fix-dynamodb-pitr-deprecation
name: Fix DynamoDB PITR Deprecation
type: Tech Debt
priority: P1
effort: Small
impact: Medium
status: shipped
created: 2026-02-02
shipped: 2026-02-20
---

# Fix DynamoDB PITR Deprecation

## Problem Statement

CDK currently shows deprecation warnings when creating DynamoDB tables:

```
[WARNING] aws-cdk-lib.aws_dynamodb.TableOptions#pointInTimeRecovery is deprecated.
  use `pointInTimeRecoverySpecification` instead
  This API will be removed in the next major release.
```

This indicates we're using deprecated CDK APIs that will be removed in future versions. Additionally, we need to establish a process to prevent using deprecated APIs in the future by leveraging the AWS documentation MCP.

## Proposed Solution

1. Update all DynamoDB table definitions to use `pointInTimeRecoverySpecification` instead of `pointInTimeRecovery`
2. Create documentation/instructions for using AWS documentation MCP when implementing CDK constructs to check for deprecated APIs
3. Consider adding a pre-commit or CI check that warns about deprecated CDK API usage

## Affected Areas

- CDK infrastructure code (DynamoDB table definitions)
- Developer documentation/workflow
- CI/CD pipeline (optional enhancement)

## Success Criteria

- [ ] No deprecation warnings for `pointInTimeRecovery` in CDK synth/deploy
- [ ] Documentation exists explaining how to use AWS docs MCP to check for deprecated APIs
- [ ] Team members are aware of the new process
