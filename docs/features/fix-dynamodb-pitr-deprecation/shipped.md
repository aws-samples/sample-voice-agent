---
id: fix-dynamodb-pitr-deprecation
name: Fix DynamoDB PITR Deprecation
type: Tech Debt
priority: P1
effort: Small
impact: Medium
created: 2026-02-02
shipped: 2026-02-20
---

# Fix DynamoDB PITR Deprecation - Shipped

## Summary

Migrated all DynamoDB table definitions from the deprecated `pointInTimeRecovery` property to `pointInTimeRecoverySpecification` with `pointInTimeRecoveryEnabled`.

## What Was Fixed

All four DynamoDB tables now use the current API:
- `crm-stack.ts` - 3 tables (Customers, Cases, Interactions)
- `session-table-construct.ts` - 1 table (Session tracking)

## Notes

This was addressed as part of the broader CDK deprecation cleanup effort (v1, v2, v3).
