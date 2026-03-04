---
id: transfer-capability
name: Transfer Capability (Local)
type: Feature
priority: P1
effort: Small
impact: Medium
created: 2026-02-19
started: 2026-02-20
shipped: 2026-02-20
---

# Transfer Capability (Local) - Shipped

## Summary

Ensured transfer and time tools are cleanly registered as core local tools within the dynamic capability registry path. The transfer tool cannot be extracted to a remote A2A agent because it requires direct access to the Pipecat `DailyTransport` for SIP REFER. This validates the hybrid architecture: some capabilities are remote (KB, CRM via A2A), others are local (transfer, time, diagnostics).

## What Was Built

### Registration in `_register_capabilities()` (`pipeline_ecs.py`)
- `_register_capabilities()` calls `_register_tools()` to get local tools (including transfer, time, echo, random, and slow variants)
- Merges local tools with remote A2A tool definitions from `AgentRegistry`
- Local tools take precedence over remote tools with the same name (conflict detection)
- Both legacy (`_register_tools()`) and registry (`_register_capabilities()`) paths work correctly

### Local Tools Registered
| Tool | Category | Why Local |
|------|----------|-----------|
| `transfer_to_agent` | SYSTEM | Requires `DailyTransport.sip_refer()` |
| `get_current_time` | SYSTEM | Trivial, no benefit from A2A overhead |
| `echo` | TESTING | Testing tool, no external dependencies |
| `slow_echo` | TESTING | Filler phrase validation tool |
| `random_number` | TESTING | Testing tool, pure in-process |
| `slow_random_number` | TESTING | Filler phrase validation tool |

## Files Changed

```
backend/voice-agent/app/pipeline_ecs.py  (registration path in _register_capabilities)
```

## Notes

No changes to the transfer tool implementation itself. The tool code from `smart-transfer-tool` (shipped 2026-02-11) is unchanged. This feature only addresses where and how it is registered in the new capability registry architecture.
