---
id: crm-capability-agent
name: CRM Capability Agent
type: Feature
priority: P1
effort: Medium
impact: High
created: 2026-02-19
started: 2026-02-19
shipped: 2026-02-20
---

# CRM Capability Agent - Shipped

## Summary

Extracted all five CRM-related tools into an independent Strands A2A capability agent deployed as its own ECS Fargate service. The CRM agent owns the CRM client, all customer/case operations, and identity verification flows. The voice agent discovers it via CloudMap and routes tool calls over A2A.

## What Was Built

### CRM Agent (`backend/agents/crm-agent/`)
- **`main.py`**: Full A2A-compliant agent with 5 tools: `lookup_customer`, `create_support_case`, `add_case_note`, `verify_account_number`, `verify_recent_transaction`. Includes ECS metadata IP detection, warm-up logic, input validation, and error handling.
- **`crm_client.py`**: Synchronous HTTP client ported from the voice agent's async `SimpleCRMService`, using `requests.Session` for persistent TCP connections. Includes `Customer` and `Case` dataclasses.
- **`Dockerfile`**: Python 3.12-slim image with healthcheck against `/.well-known/agent-card.json`
- **`requirements.txt`**: strands-agents[a2a], requests, boto3

### Infrastructure (`infrastructure/src/stacks/crm-agent-stack.ts`)
- ECS Fargate service via `CapabilityAgentConstruct` (256 CPU, 512 MiB)
- Auto-registers in CloudMap `voice-agent-capabilities` namespace
- `CRM_API_URL` passed from SSM
- Network access to CRM API endpoint

### Integration
- Voice agent discovers CRM agent via `AgentRegistry` CloudMap polling
- Agent Card auto-generated with all 5 skills
- All tools work via A2A within VPC
- CRM agent deploys independently without voice agent restart

## Files Changed

```
backend/agents/crm-agent/main.py
backend/agents/crm-agent/crm_client.py
backend/agents/crm-agent/Dockerfile
backend/agents/crm-agent/requirements.txt
infrastructure/src/stacks/crm-agent-stack.ts
```

## Dependencies

- `dynamic-capability-registry` (in progress) - AgentRegistry, A2A tool adapter, CloudMap namespace
- `simple-crm-system` (shipped) - Original CRM service code that was ported
