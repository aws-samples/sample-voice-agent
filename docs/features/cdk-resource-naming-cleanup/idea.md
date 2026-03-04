# CDK Resource Naming Cleanup

| Field     | Value     |
|-----------|-----------|
| Type      | Tech Debt |
| Priority  | P1        |
| Effort    | Medium    |
| Impact    | Medium    |
| Status    | Backlog   |

## Problem Statement

CDK resource names contain redundant segments because `projectName` already embeds the environment suffix. The default `projectName` is `voice-agent-poc` and the default `environment` is `poc`, so the standard `resourcePrefix` pattern `${projectName}-${environment}` produces `voice-agent-poc-poc`, yielding names like:

```
arn:aws:ecs:us-east-1:972801262139:cluster/voice-agent-poc-poc-voice-agent
```

This makes resources harder to identify in the console, logs, and CLI output. Every explicitly-named resource in the project is affected.

## Root Cause

**`config.ts:93-96`** sets the default `projectName` to `voice-agent-poc`, which already contains the environment name. Then every stack/construct builds:

```typescript
const resourcePrefix = `${config.projectName}-${config.environment}`;
// "voice-agent-poc" + "-" + "poc" = "voice-agent-poc-poc"
```

Additionally:
- `.env` hardcodes `PROJECT_NAME=voice-agent-poc`
- The exported `resourceName()` utility in `config.ts:167-169` is never used by any stack or construct (only in tests)
- There are **four inconsistent naming patterns** across the codebase

## Scope

### 1. Fix the `projectName` default

Change `projectName` from `voice-agent-poc` to `voice-agent` in:

- `infrastructure/src/config.ts` (line 96 default value)
- `.env` (line 15)
- `.env.example`

### 2. Standardize resource naming across all stacks

Audit and unify the four inconsistent naming patterns currently in use:

| Pattern | Used In | Example |
|---------|---------|---------|
| `${projectName}-${environment}-<suffix>` | Most stacks | `voice-agent-poc-poc-voice-agent` |
| `${projectName}-crm-<suffix>-${environment}` | CRM stack | `voice-agent-poc-crm-customers-poc` |
| `voice-agent-<type>-${environment}` | Session table, KB buckets | `voice-agent-sessions-poc` |
| `${projectName}-<type>-${environment}` | Monitoring dashboard | `voice-agent-poc-monitoring-poc` |

Decide on a single canonical pattern and apply it everywhere, or remove explicit names and let CloudFormation auto-generate them where physical name stability is not required.

### 3. Consider removing explicit names where possible

Many resources (ECS clusters, IAM roles, log groups, alarms) do not strictly need hardcoded names. Removing them:
- Avoids CloudFormation replacement issues on rename
- Lets CFN handle uniqueness
- Reduces maintenance burden

Resources that **should** keep explicit names: DynamoDB tables (referenced by name), SageMaker endpoints (referenced by name), SSM parameters.

### 4. Adopt the existing `resourceName()` utility

`config.ts` already exports a `resourceName(config, resourceType)` helper, but no stack uses it. Either adopt it project-wide or remove it to avoid dead code.

## Affected Files

| File | Explicit Names | Current Pattern |
|------|---------------|-----------------|
| `ecs-stack.ts` | clusterName, namespace, roles, logGroup, taskDef family, service | `${resourcePrefix}-*` |
| `capability-agent-construct.ts` | logGroup, roles, taskDef family, service | `${resourcePrefix}-${agentName}-agent*` |
| `sagemaker-endpoint-construct.ts` | roles, model, endpoint, config, alarms | `${resourcePrefix}-s[tt]*` |
| `voice-agent-monitoring-construct.ts` | dashboard, SNS topic, alarms, logGroup, queries | `${resourcePrefix}-*` |
| `knowledge-base-construct.ts` | role, logGroup, lambda | Mixed patterns |
| `session-counter-lambda-construct.ts` | logGroup, lambda, event rule | `${resourcePrefix}-session-counter*` |
| `session-table-construct.ts` | tableName | Hardcoded `voice-agent-sessions-` |
| `crm-stack.ts` | tables, API, alarms, dashboard | Unique `${projectName}-crm-*-${env}` |
| `kb-agent-stack.ts` | cluster import | `${resourcePrefix}-voice-agent` |
| `crm-agent-stack.ts` | cluster import | `${resourcePrefix}-voice-agent` |
| `agentcore-runtime-construct.ts` | ECR repo, role, runtime name | `${resourcePrefix}-*` |
| `vpc-construct.ts` | SG descriptions only | `${resourcePrefix}` in descriptions |
| `config.ts` | `resourceName()` utility | Unused |

## Migration Risk

Changing `projectName` will alter the physical names of **every explicitly-named resource**, which triggers CloudFormation **replacement** (delete + create) for most resource types. This includes IAM roles, ECS clusters/services, SageMaker endpoints, DynamoDB tables, Lambda functions, log groups, and S3 buckets.

**Recommended approach:**
1. For non-stateful resources (roles, clusters, services, alarms), accept the replacement
2. For stateful resources (DynamoDB tables, S3 buckets), either keep current names or plan data migration
3. Consider a phased approach: first remove unnecessary explicit names, then fix the prefix

## Acceptance Criteria

- [ ] No resource names contain repeated segments (e.g., `poc-poc`, `prod-prod`)
- [ ] A single, documented naming convention is used across all stacks
- [ ] The `resourceName()` utility is either adopted everywhere or removed
- [ ] `cdk synth` succeeds with no naming-related drift from the chosen convention
- [ ] CDK tests updated to reflect new naming patterns
