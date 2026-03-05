# Expanded Tool Result Logging

| Field     | Value       |
|-----------|-------------|
| Type      | Enhancement |
| Priority  | P2          |
| Effort    | Medium      |
| Impact    | Medium      |

## Problem Statement

The dashboard and conversation logs capture that A2A tool calls happened (skill ID, elapsed time, response length), but do not surface what the tools actually returned. When reviewing a call, an operator sees that `search_knowledge_base` was called and returned 4,672 bytes in 960ms, but cannot see what knowledge base content was retrieved. Similarly, `verify_account_number` shows success but not what was verified or the outcome.

This makes it difficult to:
- Debug incorrect agent behavior (did the KB return the right content?)
- Audit customer interactions (what data was looked up?)
- Understand why an agent made a particular recommendation

## Observed Behavior

From test call #4 logs:

```json
{"skill_id": "search_knowledge_base", "elapsed_ms": 960, "response_length": 4672, "event": "flow_a2a_call_success"}
{"skill_id": "verify_account_number", "elapsed_ms": 3693, "response_length": 156, "event": "flow_a2a_call_success"}
{"skill_id": "lookup_customer", "elapsed_ms": 2294, "response_length": 695, "event": "flow_a2a_call_success"}
```

The `response_length` tells us data came back, but not what it contained.

## Expected Behavior

- Tool result summaries should be logged at an appropriate detail level
- For KB searches: log the retrieved document titles/snippets and confidence scores
- For CRM lookups: log the customer name, ID, and key fields found
- For verification tools: log the verification outcome (verified/failed) and what was checked
- For appointment tools: log the appointment details (date, time, type, ID)
- Full response text should be available at DEBUG level; structured summaries at INFO level
- Dashboard saved queries should be able to surface tool result details

## Investigation Areas

- `app/flows/flow_config.py`: `_create_a2a_flow_function()` -- the `flow_a2a_call_success` log event has `response_length` but not the response content
- Consider adding a `response_summary` field (first N chars or structured extract) to the success log
- Consider a separate `tool_result_detail` log event at DEBUG level with the full response
- `app/observability.py`: `ConversationObserver` -- could tool results be captured as part of the conversation record?
- Privacy considerations: customer PII in tool results should be handled carefully in logs
