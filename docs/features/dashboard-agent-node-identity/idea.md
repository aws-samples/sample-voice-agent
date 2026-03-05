# Agent Node Identity in Dashboard

| Field     | Value       |
|-----------|-------------|
| Type      | Enhancement |
| Priority  | P1          |
| Effort    | Medium      |
| Impact    | High        |

## Problem Statement

The CloudWatch dashboard and log insights queries currently show a generic "agent" label instead of identifying which specific agent node is active during each conversation turn. When reviewing call logs or the dashboard, an operator cannot tell whether a given turn happened in the KB agent, CRM agent, or Appointment agent without cross-referencing transition timestamps.

The `agent_node` dimension is already emitted in `turn_completed` events and set via `MetricsCollector.set_agent_node()`, but the dashboard widgets and saved queries do not surface this information effectively.

## Observed Behavior

- Dashboard conversation view shows turns attributed to a generic "agent" role
- Log Insights queries return `agent_node` in raw JSON but it is not surfaced in the dashboard widgets
- An operator reviewing a multi-agent call cannot quickly see the agent progression (e.g., orchestrator -> KB -> CRM -> appointment) in the dashboard

## Expected Behavior

- Each conversation turn in the dashboard should show which agent node produced it (e.g., "KB Agent", "CRM Agent", "Appointment Agent")
- The Multi-Agent Flows dashboard row should include a widget showing the agent node timeline for a call
- Log Insights saved queries should filter/group by `agent_node`
- Consider a visual timeline or swimlane view showing agent transitions

## Investigation Areas

- `infrastructure/src/constructs/voice-agent-monitoring-construct.ts`: Dashboard row 11 (Multi-Agent Flows) and saved queries
- `app/observability.py`: `turn_completed` event already includes `agent_node` field
- `app/observability.py`: `conversation_turn` event -- does it include `agent_node`?
- CloudWatch Log Insights query syntax for grouping by `agent_node`
