# Clean Up CDK Deprecations

| Field     | Value     |
|-----------|-----------|
| Type      | Tech Debt |
| Priority  | P1        |
| Effort    | Small     |
| Impact    | Medium    |
| Status    | Shipped   |

## Problem Statement

CDK synth produces deprecation warnings for APIs that will be removed in the next major release. These must be migrated to avoid breakage during CDK upgrades and to keep the build output clean.

Current warnings observed during `cdk synth`:

```
[WARNING] aws-cdk-lib.aws_logs.QueryStringProps#stats is deprecated.
  Use `statsStatements` instead

[WARNING] aws-cdk-lib.aws_dynamodb.TableOptions#pointInTimeRecovery is deprecated.
  use `pointInTimeRecoverySpecification` instead
  (3 occurrences)
```

## Scope

This is a comprehensive audit — not just the warnings above. The full approach:

1. Run `cdk synth` and capture all `[WARNING]` deprecation lines
2. Fix each deprecated API usage
3. Grep the codebase for any deprecated APIs that may not emit runtime warnings
4. Verify zero deprecation warnings on clean synth

## Known Deprecations

| Deprecated API | Replacement | File(s) |
|----------------|-------------|---------|
| `QueryStringProps#stats` | `statsStatements` (string[]) | `voice-agent-monitoring-construct.ts` |
| `TableOptions#pointInTimeRecovery` | `pointInTimeRecoverySpecification` | `crm-stack.ts` (3 tables) |
| Any others found during audit | TBD | TBD |

## Notes

- Previous cleanup rounds addressed `containerInsights` (v1) and `logRetention` (v2)
- The `url.parse()` Node.js deprecation may come from external dependencies and is out of scope unless it originates in our code
- Consider adding a CI step that fails on deprecation warnings to prevent regressions

## Acceptance Criteria

- [ ] `cdk synth` produces zero `[WARNING]` deprecation lines
- [ ] All deprecated API usages replaced with current equivalents
- [ ] TypeScript compiles with no errors
- [ ] Existing CDK tests pass
