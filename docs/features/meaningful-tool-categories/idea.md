# Meaningful Tool Categories

| Field     | Value       |
|-----------|-------------|
| Type      | Tech Debt   |
| Priority  | P2          |
| Effort    | Small       |
| Impact    | Low         |

## Problem Statement

All A2A tool executions are recorded with `category: "a2a"` regardless of what they actually do. A KB search, a customer lookup, an account verification, and an appointment booking all share the same category. This makes it difficult to filter, group, or analyze tool usage by functional domain in the dashboard and metrics.

From test call #4:

```json
{"tool_name": "search_knowledge_base", "category": "a2a", "status": "success"}
{"tool_name": "verify_account_number", "category": "a2a", "status": "success"}
{"tool_name": "lookup_customer", "category": "a2a", "status": "success"}
{"tool_name": "create_support_case", "category": "a2a", "status": "success"}
{"tool_name": "check_availability", "category": "a2a", "status": "success"}
{"tool_name": "book_appointment", "category": "a2a", "status": "success"}
```

All six different tools across three different agents share the same "a2a" category.

## Observed Behavior

- `MetricsCollector.record_tool_execution()` is called with `category="a2a"` for all A2A tools
- The `ToolExecutionTime` CloudWatch metric uses category as a dimension, but "a2a" provides no differentiation
- Dashboard filtering by category cannot distinguish KB operations from CRM operations from scheduling operations

## Expected Behavior

- Tools should have domain-relevant categories like `knowledge_base`, `crm`, `scheduling`, `verification`
- Categories could be derived from the agent name (KB agent tools -> `knowledge_base` category)
- Categories could be derived from Agent Card metadata (skill tags, agent description)
- The `ToolCategory` enum in `app/tools/schema.py` already has values like `KNOWLEDGE_BASE`, `CRM`, `CUSTOMER_INFO` -- A2A tools should map to these
- Dashboard metrics should be filterable by meaningful category

## Investigation Areas

- `app/flows/flow_config.py`: `_create_a2a_flow_function()` -- where `record_tool_execution(category="a2a")` is called
- `app/tools/schema.py`: `ToolCategory` enum -- existing categories that could be reused
- Agent Card metadata: agent name or description could be parsed to infer category
- Consider adding a `category` field to `AgentSkillInfo` or deriving it from the agent's CloudMap service name
- `app/observability.py`: `MetricsCollector.record_tool_execution()` -- how category is used in EMF metrics
