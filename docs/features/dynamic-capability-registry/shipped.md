---
id: dynamic-capability-registry
name: Dynamic Capability Registry
type: Feature
priority: P0
effort: Medium
impact: High
created: 2026-02-19
started: 2026-02-19
shipped: 2026-02-20
---

# Dynamic Capability Registry - Shipped

## Summary

Replaced the voice agent's hard-wired tool/observer/prompt assembly with a dynamic, A2A-based capability architecture. Capabilities are independently deployed ECS Fargate services that self-register via AWS CloudMap and self-describe via standard A2A Agent Cards. The voice agent discovers capabilities at runtime and maps A2A skills to Pipecat tools.

## What Was Built

### Voice Agent A2A Integration (`app/a2a/`)
- **`discovery.py`**: CloudMap service discovery using aioboto3
- **`registry.py`**: AgentRegistry with background polling (30s), A2AAgent caching, atomic routing table swap
- **`tool_adapter.py`**: Bridges A2A skills into Pipecat tool handlers with Bedrock tool spec generation

### Pipeline Integration (`pipeline_ecs.py`)
- `_register_capabilities()`: Merges remote A2A tools with local tools (transfer, time, diagnostics)
- Feature flag gating: `ENABLE_CAPABILITY_REGISTRY` SSM parameter
- Local tools take precedence on name conflicts

### Infrastructure
- CloudMap HTTP namespace (`voice-agent-capabilities`) in ECS stack
- Reusable `CapabilityAgentConstruct` CDK construct for deploying any A2A capability agent
- KB Agent stack (`kb-agent-stack.ts`) and CRM Agent stack (`crm-agent-stack.ts`)
- IAM permissions for `servicediscovery:DiscoverInstances`

### Capability Agents Deployed
- **Knowledge Base Agent**: Strands agent with `search_knowledge_base` tool + DirectToolExecutor
- **CRM Agent**: Strands agent with 5 tools (lookup, cases, notes, verification)
- Both auto-register in CloudMap and serve Agent Cards at `/.well-known/agent-card.json`

### Architecture Validated
- Hub-and-spoke: voice agent orchestrates, capability agents execute
- Hybrid local/remote: transfer stays local (needs DailyTransport), KB/CRM go remote
- Model-driven tool use: LLM reasons from tool descriptions alone, no prompt fragments

## Test Results
- 404 voice agent tests pass
- 126 CDK tests pass (39 new)

## Files Changed

```
New:
  backend/voice-agent/app/a2a/__init__.py
  backend/voice-agent/app/a2a/discovery.py
  backend/voice-agent/app/a2a/registry.py
  backend/voice-agent/app/a2a/tool_adapter.py
  backend/agents/knowledge-base-agent/
  backend/agents/crm-agent/
  infrastructure/src/constructs/capability-agent-construct.ts
  infrastructure/src/stacks/kb-agent-stack.ts
  infrastructure/src/stacks/crm-agent-stack.ts

Modified:
  backend/voice-agent/app/pipeline_ecs.py
  backend/voice-agent/app/service_main.py
  backend/voice-agent/app/services/config_service.py
  infrastructure/src/stacks/ecs-stack.ts
  infrastructure/src/main.ts
```
