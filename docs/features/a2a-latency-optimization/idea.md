---
id: a2a-latency-optimization
name: A2A Tool Call Latency Optimization
type: Feature
priority: P2
effort: Medium
impact: High
status: shipped
created: 2026-02-20
shipped: 2026-02-20
---

# A2A Tool Call Latency Optimization

## Problem

A2A tool calls currently take ~5 seconds end-to-end (observed: 5009ms for
`search_knowledge_base`). This includes A2A protocol overhead, Strands agent
initialization, and the actual Bedrock KB retrieval. For a voice pipeline
targeting sub-2s E2E latency, this adds significant perceived delay.

## Potential Optimizations

1. **Strands agent warm-up** - Pre-initialize the Strands agent on container
   start rather than lazily on first request. The `MetricsClient` creation
   logged mid-request suggests cold-start overhead.

2. **A2A streaming compliance** - Set `enable_a2a_compliant_streaming=True`
   on `A2AServer` to use proper spec-compliant streaming, which may allow
   partial results to flow back sooner.

3. **Connection pooling** - The `A2AAgent` client creates new HTTP connections
   per request. Persistent connections to known agents could reduce TCP/TLS
   setup time.

4. **Parallel tool execution** - When the LLM requests multiple tools
   simultaneously, execute A2A calls in parallel rather than sequentially.

5. **Response caching** - Cache KB retrieval results for repeated queries
   within a session to avoid redundant round-trips.

## Measurement

- Current baseline: ~5000ms for KB search via A2A
- Target: <2000ms for KB search via A2A
- Metric: `ToolExecutionTime` dimension `tool_name=search_knowledge_base`
