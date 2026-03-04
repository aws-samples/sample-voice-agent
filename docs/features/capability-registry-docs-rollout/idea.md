---
name: Capability Registry Documentation & Rollout
type: feature
priority: P2
effort: medium
impact: medium
status: shipped
created: 2026-02-20
shipped: 2026-02-20
related-to: dynamic-capability-registry
depends-on: dynamic-capability-registry
---

# Capability Registry Documentation & Rollout

## Problem Statement

Phases 1-5 of the Dynamic Capability Registry are code-complete and tested, but not yet deployed or validated end-to-end in a real environment. Before writing documentation or rolling out to production, we need to:

1. Deploy the infrastructure (CloudMap namespace, KB agent, CRM agent)
2. Validate CloudMap discovery, Agent Card generation, and A2A tool calls work in-VPC
3. Measure actual latency overhead
4. Confirm model-driven tool use works without custom prompt fragments

Once validated, developer documentation and CLAUDE.md updates are needed so others can create new capability agents.

## Blocked By: Deployment Validation

The following items from the plan (Phases 4.3 and 5 validation) must pass before this work begins:

- [ ] Deploy KB agent stack, verify CloudMap registration
- [ ] Verify Agent Card at `/.well-known/agent.json` from within VPC
- [ ] Deploy CRM agent stack, verify CloudMap registration and all 5 tools
- [ ] Deploy voice agent with `ENABLE_CAPABILITY_REGISTRY=true`
- [ ] Verify AgentRegistry discovers both agents via CloudMap polling
- [ ] Verify LLM calls `search_knowledge_base` via A2A (KB agent)
- [ ] Verify LLM calls all 5 CRM tools via A2A (CRM agent)
- [ ] Measure E2E latency: target <50ms added overhead per A2A call within VPC
- [ ] Verify filler phrases work correctly for A2A tool calls
- [ ] Verify model-driven tool use (no custom prompt fragments needed)
- [ ] Confirm research items R2 (variable latency handlers), R3 (CloudMap latency), R4 (ECS auto-register/deregister)

## Scope

### 6.1 Developer Documentation

- [ ] How to create a new capability agent with Strands SDK (step-by-step guide):
  - Define `@tool` functions with explicit docstrings (these ARE the tool descriptions the LLM sees)
  - Create `Agent(tools=[...])` + `A2AServer(agent=...)`
  - Dockerfile + requirements.txt pattern
  - CDK stack using `CapabilityAgentConstruct`
  - Deploy -- voice agent discovers it automatically within 30-60s
- [ ] `CapabilityAgentConstruct` CDK construct usage reference
- [ ] Architecture diagram and data flow (can reference `plan.md` diagram)
- [ ] Tool description best practices (model-driven tool use relies on descriptions alone)

### 6.2 Update CLAUDE.md

- [ ] Add `ENABLE_CAPABILITY_REGISTRY` env var
- [ ] Add `A2A_NAMESPACE` env var
- [ ] Add A2A config SSM paths (`/voice-agent/a2a/*`)
- [ ] Document new CloudWatch metrics for A2A calls (if any added during validation)
- [ ] Note `strands-agents[a2a]>=1.27.0` dependency for capability agents

### 6.3 Remove Legacy Code Path (deferred)

After production validation and confidence:
- [ ] Make capability registry the default (`enable_capability_registry` defaults to `true`)
- [ ] Remove `_register_tools()` and inline KB/CRM prompt assembly from `pipeline_ecs.py`
- [ ] Remove feature flag
- [ ] Update all tests

## Estimated Effort

| Task | Effort |
|------|--------|
| Developer docs (step-by-step guide) | 0.5 day |
| CLAUDE.md updates | 0.25 day |
| Architecture diagram cleanup | 0.25 day |
| Legacy code removal (6.3, later) | 0.5 day |
| **Total** | **~1.5 days** |

## Dependencies

- All deployment validation items above must pass first
- `dynamic-capability-registry` Phases 1-5 (code-complete)
- `knowledge-base-capability-agent` (code-complete, needs deployment)
- `crm-capability-agent` (code-complete, needs deployment)
