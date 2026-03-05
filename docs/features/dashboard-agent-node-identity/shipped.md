---
id: dashboard-agent-node-identity
name: Dashboard Agent Node Identity
type: enhancement
priority: P1
effort: Medium
impact: High
status: shipped
created: 2026-03-05
started: 2026-03-05
shipped: 2026-03-05
---

# Shipped: Dashboard Agent Node Identity

## Summary

Surfaced the `agent_node` dimension -- already emitted in `turn_completed` events -- throughout the CloudWatch dashboard, conversation logs, and saved queries. Each conversation turn now shows which specialist agent (KB, CRM, Appointment, Orchestrator) produced it. No new metrics or dimensions were needed; this was purely a dashboard and log enrichment change.

## What Was Built

### Conversation Log Enrichment
- Added `agent_node` field to `conversation_turn` log events in `ConversationObserver._log_conversation_turn()`
- Enables filtering and grouping conversation transcripts by active agent

### Dashboard Widgets (Row 11 -- Multi-Agent Flows)
- "Response Latency by Agent Node" widget using SEARCH expression across agent nodes
- "Tool Execution by Agent Node" widget using SEARCH expression
- "Agent Node Timeline (Last 1h)" Log Insights query widget showing agent progression

### Saved Query Updates
- Updated `flow-conversation-trace` query to include `agent_node`
- Updated `conversation-flow` query to include `agent_node`
- Updated `trace-call` query to include `agent_node`
- Added new `agent-node-progression` saved query for tracking node transitions over time

## Files Changed

### Modified Files
- `app/observability.py` -- `agent_node` in conversation_turn events
- `infrastructure/src/constructs/voice-agent-monitoring-construct.ts` -- 3 new widgets, 4 saved query updates
- `tests/test_observability_metrics.py` -- test updates

## Quality Gates

### QA Validation: PASS
- 194/194 CDK tests passing
- All success criteria verified
- Dashboard widgets render correctly with SEARCH expressions

### Security Review: PASS
- No new data emitted -- `agent_node` was already present in `turn_completed` events
- No PII implications
- Dashboard is internal CloudWatch, access controlled by IAM
