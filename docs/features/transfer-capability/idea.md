---
name: Transfer Capability (Local)
type: feature
priority: P1
effort: small
impact: medium
status: shipped
created: 2026-02-19
shipped: 2026-02-20
related-to: dynamic-capability-registry
depends-on: dynamic-capability-registry
---

# Transfer Capability (Local)

## Problem Statement

The transfer tool (`transfer_to_agent`) and time tool (`get_current_time`) are currently registered alongside all other tools in the monolithic `_register_tools()` function in `pipeline_ecs.py`. When the dynamic capability registry replaces `_register_tools()` with `_register_capabilities()`, these tools need a clean registration path.

Unlike KB and CRM, the transfer tool **cannot be extracted to a remote A2A agent** because it requires direct access to the Pipecat `DailyTransport` object to execute SIP REFER for call transfers. The transport is a local pipeline resource -- there's no way to proxy it over A2A.

This feature ensures transfer and time tools are cleanly registered as **core local tools** within the capability registry path, rather than being left behind in legacy code.

## Vision

Define transfer and time as **core local capabilities** that are always available in the dynamic capability registry path. They register directly with the LLM (same as today) without going through A2A. This validates the hybrid architecture: some capabilities are remote (KB, CRM via A2A), others are local (transfer, diagnostics).

The transfer tool stays in-process but benefits from the cleaner registration architecture -- its configuration (`TRANSFER_DESTINATION`), tool definition, and handler are co-located rather than spread across `_register_tools()` and inline environment variable reads.

## Scope

### Tools That Stay Local

| Current File | Tool Name | Category | Why Local |
|---|---|---|---|
| `transfer_tool.py` | `transfer_to_agent` | `SYSTEM` | Requires `DailyTransport.sip_refer()` -- needs local pipeline access |
| `time_tool.py` | `get_current_time` | `SYSTEM` | Trivial, no benefit from A2A overhead |

### Diagnostic/Testing Tools (Also Stay Local)

| Current File | Tool Name | Category | Why Local |
|---|---|---|---|
| `echo_tool.py` | `echo` | `TESTING` | Testing tool, no external dependencies |
| `slow_echo_tool.py` | `slow_echo` | `TESTING` | Testing tool for filler phrase validation |
| `random_number_tool.py` | `random_number` | `TESTING` | Testing tool, pure in-process |
| `slow_random_tool.py` | `slow_random_number` | `TESTING` | Testing tool for filler phrase validation |

### Service Dependencies (Local)

- **`context.transport`** -- Pipecat `DailyTransport` object for SIP REFER
- **`context.sip_session_id`** -- SIP session tracking for transfers
- **`TRANSFER_DESTINATION`** -- SIP URI environment variable

## Technical Approach

### In `_register_capabilities()`

When the capability registry is enabled, local tools are registered directly alongside dynamically discovered remote tools:

```python
async def _register_capabilities(llm, session_id, transport, collector, sip_tracker):
    """Register both remote A2A capabilities and core local tools."""
    
    # 1. Get remote tools from AgentRegistry (KB, CRM, etc.)
    registry = get_agent_registry()
    remote_tool_specs = registry.get_tool_definitions()
    for skill_id, entry in registry.get_routing_table().items():
        handler = create_a2a_tool_handler(skill_id, entry.a2a_agent)
        llm.register_function(function_name=skill_id, handler=handler)
    
    # 2. Register core local tools (transfer, time, diagnostics)
    local_tool_specs = _register_local_tools(llm, session_id, transport, collector, sip_tracker)
    
    # 3. Return combined specs
    return remote_tool_specs + local_tool_specs
```

### Transfer Tool -- No Code Change Needed

The transfer tool implementation itself doesn't change. The only change is where it's registered -- from `_register_tools()` to `_register_local_tools()` (a cleaner subset of the current function).

### Optional: Modularize Transfer

As a follow-up, the transfer tool could be reorganized into a self-contained module:

```
backend/voice-agent/app/capabilities/transfer/
    __init__.py          # Exports tool definitions + registration helper
    transfer_tool.py     # Moved from tools/builtin/
    time_tool.py         # Moved from tools/builtin/
```

This is optional -- the tools work fine in their current location. The key deliverable is clean registration in the new `_register_capabilities()` path.

## Affected Areas

- Modified: `pipeline_ecs.py` -- new `_register_local_tools()` function called from `_register_capabilities()`
- No new files required (tools stay in `app/tools/builtin/`)
- No infrastructure changes (no ECS service, no CloudMap registration)

## Validation Criteria

- [ ] Transfer tool works correctly when `ENABLE_CAPABILITY_REGISTRY=true`
- [ ] SIP REFER executes successfully for call transfers (same as today)
- [ ] Time tool returns correct UTC time
- [ ] Diagnostic tools (echo, random, slow variants) work for testing
- [ ] Local tools appear alongside remote A2A tools in the LLM's tool list
- [ ] Filler phrases work for slow local tools (slow_echo, slow_random)
- [ ] `TRANSFER_DESTINATION` not configured: tool returns clear error message (same as today)

## Dependencies

- `dynamic-capability-registry` -- Must be implemented first (`_register_capabilities()` function)
- `smart-transfer-tool` (shipped) -- Existing transfer tool code, unchanged
- No new Python packages required
