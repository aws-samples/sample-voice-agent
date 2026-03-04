---
name: A2A Capability Gating
type: feature
priority: P2
effort: small
impact: medium
status: idea
created: 2026-02-23
related-to: dynamic-capability-registry, dtmf-input-capture, call-recording-capability
depends-on: []
---

# A2A Capability Gating

## Problem Statement

The local tool capability system (`PipelineCapability` + `detect_capabilities()`) filters local tools based on what the pipeline can provide at runtime (transport, SIP session, DTMF, recording control, etc.). However, remote A2A tools discovered via CloudMap are **unconditionally registered** with the LLM -- there is no mechanism for a remote skill to declare pipeline capability requirements.

This means if a future A2A capability agent exposes a skill that requires SIP transport (e.g., a remote transfer orchestration agent), it would be registered even in WebRTC-only pipelines where it cannot function. The LLM would see the tool, attempt to use it, and get a runtime error.

Additionally, the `disabled-tools` SSM override (`/voice-agent/config/disabled-tools`) only applies to local tools. Remote A2A skills cannot be explicitly disabled via config.

## Proposed Solution

Use the existing `tags` field on A2A Agent Card skills to encode capability requirements with a `requires:` prefix convention.

### Agent-side (capability agent)

Capability agents declare requirements via tags on their `@tool` functions:

```python
@tool(tags=["requires:sip_session", "requires:transport"])
def transfer_via_orchestrator(query: str) -> dict:
    """Orchestrate a complex multi-party transfer."""
    ...
```

### Hub-side (voice agent)

In `_register_capabilities()`, filter remote skills the same way local tools are filtered:

1. Parse `requires:*` tags from `AgentSkillInfo.tags` into a `FrozenSet[PipelineCapability]`
2. Check `skill.requires <= available_capabilities` (subset test)
3. Skip skills whose requirements aren't met, log `a2a_tool_skipped_missing_capabilities`
4. Also apply `disabled_tools` SSM override to remote skills

### Registry changes

Add a `requires` property to `AgentSkillInfo`:

```python
@property
def requires(self) -> FrozenSet[PipelineCapability]:
    caps = set()
    for tag in self.tags:
        if tag.startswith("requires:"):
            cap_value = tag[len("requires:"):]
            try:
                caps.add(PipelineCapability(cap_value))
            except ValueError:
                pass  # Unknown capability tag, skip
    return frozenset(caps)
```

## Why Not Now

No current A2A agents need pipeline capabilities. The KB agent searches Bedrock Knowledge Bases (pure backend). The CRM agent does customer lookups and case management (pure backend). Neither requires transport, SIP, or any pipeline internals.

This becomes important when:
- A remote agent needs to trigger pipeline actions (e.g., orchestrated transfers, recording control)
- The `disabled-tools` SSM override needs to work uniformly across local and remote tools
- DTMF or recording capabilities are added and remote agents need to gate on them

## Scope

### Files to modify

- `app/a2a/registry.py` -- Add `requires` property to `AgentSkillInfo`, parse `requires:*` tags
- `app/pipeline_ecs.py` -- Filter remote skills by capabilities in `_register_capabilities()`, apply `disabled_tools` to remote skills
- `tests/test_a2a_pipeline_integration.py` -- Test capability filtering for remote skills
- `tests/test_a2a_registry.py` -- Test `AgentSkillInfo.requires` parsing

### Estimated effort

Small -- ~2-3 hours. The filtering logic already exists for local tools; this extends it to remote skills using the same `available_capabilities` frozenset.
