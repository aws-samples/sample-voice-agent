---
shipped: 2026-01-27
---

# Shipped: CDK Deprecation Cleanup

## Summary

Fixed all CDK-related deprecation warnings by migrating to the recommended APIs:
- `containerInsights` → `containerInsightsV2` with `ENHANCED` setting
- `logRetention` → explicit `logGroup` resource

## Key Changes

### ECS Cluster (containerInsights)

**File**: `src/stacks/ecs-stack.ts:112`

```typescript
// Before (deprecated)
containerInsights: true,

// After
containerInsightsV2: ecs.ContainerInsights.ENHANCED,
```

### Lambda Log Group (logRetention)

**File**: `src/constructs/session-counter-lambda-construct.ts`

```typescript
// Before (deprecated)
logRetention: logs.RetentionDays.ONE_WEEK,

// After
const logGroup = new logs.LogGroup(this, 'SessionCounterLogGroup', {
  logGroupName: `/aws/lambda/${resourcePrefix}-session-counter`,
  retention: logs.RetentionDays.ONE_WEEK,
  removalPolicy: cdk.RemovalPolicy.DESTROY,
});
// ... then pass logGroup to Lambda function
```

### Test Update

**File**: `test/stacks.test.ts`

Updated test assertion to expect `enhanced` instead of `enabled` for container insights.

## Migration Process for logRetention

The `logRetention` → `logGroup` migration required special handling:

1. **Disable EventBridge rule** - Stop Lambda invocations temporarily
2. **Delete existing log group** - Remove the auto-created log group
3. **Deploy CDK changes** - Create new `LogGroup` resource
4. **EventBridge rule re-enabled** - Deployment re-enables the schedule

This was necessary because Lambda auto-creates log groups when invoked, causing conflicts with CDK-managed `LogGroup` resources.

## Warnings Status (Final)

| Warning | Status | Notes |
|---------|--------|-------|
| `containerInsights` deprecated | ✅ Fixed | Migrated to `containerInsightsV2` |
| `logRetention` deprecated | ✅ Fixed | Migrated to explicit `logGroup` |
| `url.parse()` Node.js | ℹ️ External | CDK dependency issue, not our code |
| `minHealthyPercent` | ℹ️ Info | Informational, not a deprecation |

## Resources Cleaned Up

The deployment automatically removed the old LogRetention infrastructure:
- `LogRetention` custom resource
- `LogRetention` Lambda function
- `LogRetention` IAM role and policy

## Testing

- All 71 CDK tests passing
- Deployed to production successfully
- Lambda logs verified in new CDK-managed log group
- CloudWatch Container Insights metrics verified

## Sources

- [CDK Issue #35003: Migrate from logRetention to logGroup](https://github.com/aws/aws-cdk/issues/35003)
- [CDK Issue #36106: logRetention Deprecation Status](https://github.com/aws/aws-cdk/issues/36106)
- [AWS CDK ContainerInsights Enum](https://docs.aws.amazon.com/cdk/api/v2/docs/aws-cdk-lib.aws_ecs.ContainerInsights.html)
