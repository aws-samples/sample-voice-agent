---
id: a2a-latency-optimization
name: A2A Tool Call Latency Optimization
type: Feature
priority: P2
effort: Medium
impact: High
created: 2026-02-20
started: 2026-02-20
shipped: 2026-02-20
---

# A2A Tool Call Latency Optimization - Shipped

## Summary

Reduced A2A tool call latency from ~5,000ms to <1,000ms through a combination of optimizations. The biggest win was the DirectToolExecutor pattern for the KB agent, which bypasses the inner Strands LLM entirely.

## What Was Built

### DirectToolExecutor (KB Agent)
- Custom executor that bypasses inner Strands LLM for single-tool agents
- Calls `search_knowledge_base` directly via `asyncio.to_thread()`
- **Results:** ToolExecutionTime reduced from 2,742ms to 323ms (88% reduction)

### Agent Warm-Up
- KB + CRM agents pre-initialize boto3 clients and probe Strands agent on container start
- Eliminates first-call cold start overhead

### Two-Layer Caching
- KB agent: TTLCache (query -> result, 60s TTL, 100 max entries)
- A2A adapter: TTLCache (skill+query -> response, 60s TTL) - cache hits skip entire A2A round-trip

### Connection Pooling
- CRM agent: `requests.Session` for persistent TCP connections
- Voice agent CRM service: shared `aiohttp.ClientSession` with `TCPConnector(limit=10, keepalive_timeout=30)`

### Instrumentation
- Sub-phase timing in KB agent, CRM agent, and A2A tool adapter
- Fixed metrics bug: `tool_adapter.py` now correctly emits `ToolExecutionTime` metrics

### Parallel Tool Execution
- Confirmed Pipecat already supports parallel dispatch via `_run_parallel_function_calls()` - no changes needed

## Key Results

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| KB search ToolExecutionTime | 2,742ms | 323ms | 88% reduction |
| AgentResponseLatency | 1,598ms | 918ms | 43% reduction |

## Files Changed

```
backend/agents/knowledge-base-agent/main.py       # DirectToolExecutor, warm-up, caching
backend/agents/knowledge-base-agent/requirements.txt
backend/agents/crm-agent/main.py                  # Warm-up, timing
backend/agents/crm-agent/crm_client.py             # Connection pooling (requests.Session)
backend/voice-agent/app/a2a/tool_adapter.py        # Caching, timing, metrics fix
backend/voice-agent/app/a2a/registry.py            # Discovery timing
backend/voice-agent/app/services/crm_service.py    # aiohttp session reuse
```
