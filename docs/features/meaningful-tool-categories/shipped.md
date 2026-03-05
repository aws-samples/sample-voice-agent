---
id: meaningful-tool-categories
name: Meaningful Tool Categories
type: tech-debt
priority: P2
effort: Small
impact: Low
status: shipped
created: 2026-03-05
started: 2026-03-05
shipped: 2026-03-05
---

# Shipped: Meaningful Tool Categories

## Summary

Replaced the generic `category: "a2a"` on all A2A tool executions with domain-relevant categories derived from CloudMap service names. KB search is now `KNOWLEDGE_BASE`, customer lookup is `CRM`, appointment booking is `CUSTOMER_SERVICE`. This enables filtering, grouping, and analyzing tool usage by functional domain in CloudWatch metrics and the Call Flow Visualizer.

## What Was Built

### Category Resolution (`app/a2a/categories.py`)
- `resolve_tool_category(agent_name: str) -> ToolCategory` function
- Substring matching from CloudMap service name to `ToolCategory` enum:
  - `kb-agent` -> `ToolCategory.KNOWLEDGE_BASE`
  - `crm-agent` -> `ToolCategory.CRM`
  - `appointment-agent` -> `ToolCategory.CUSTOMER_SERVICE`
  - Unknown agents -> `ToolCategory.SYSTEM` (fallback)

### A2A Tool Adapter Integration
- Non-Flows path (`tool_adapter.py`): replaced 4 hardcoded `category="a2a"` occurrences with resolved category
- Flows path (`flow_config.py`): threaded resolved category through Flows A2A function wrappers

### Filler Phrase Integration
- Added `CUSTOMER_SERVICE` category to filler phrase mappings for contextual delay messages

## Files Changed

### New Files
- `app/a2a/categories.py` -- category resolution utility
- `tests/test_a2a_categories.py` -- unit tests

### Modified Files
- `app/a2a/tool_adapter.py` -- use resolved categories instead of hardcoded "a2a"
- `app/flows/flow_config.py` -- thread categories through Flows adapter
- `app/tools/filler_phrases.py` -- CUSTOMER_SERVICE filler phrase mappings
- Existing test files -- updated for new category values

## Quality Gates

### QA Validation: PASS
- Unit tests for category resolution covering all known agents and fallback
- Existing tool execution tests updated for new category values
- CloudWatch metrics verified: tool executions grouped by meaningful category

### Security Review: PASS
- Read-only mapping from service names to enum values -- no new data flows
- Fallback to SYSTEM for unknown agents prevents information leakage
- No PII implications
