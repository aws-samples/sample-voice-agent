---
id: knowledge-base-capability-agent
name: Knowledge Base Capability Agent
type: Feature
priority: P1
effort: Medium
impact: High
created: 2026-02-19
started: 2026-02-19
shipped: 2026-02-20
---

# Knowledge Base Capability Agent - Shipped

## Summary

Extracted the knowledge base search tool from the voice agent into an independent Strands A2A capability agent deployed as its own ECS Fargate service. The voice agent discovers it via CloudMap and routes tool calls over A2A within the VPC.

## What Was Built

### KB Agent (`backend/agents/knowledge-base-agent/`)
- **`main.py`**: Full A2A-compliant agent with `search_knowledge_base` tool using Bedrock KB retrieval, confidence filtering, S3 source extraction, and response caching
- **`DirectToolExecutor`**: Custom executor that bypasses the inner Strands LLM, reducing A2A tool latency from ~2,742ms to ~323ms
- **`Dockerfile`**: Python 3.12-slim image with healthcheck against `/.well-known/agent-card.json`
- **`requirements.txt`**: strands-agents[a2a], boto3, requests, cachetools

### Infrastructure (`infrastructure/src/stacks/kb-agent-stack.ts`)
- ECS Fargate service via `CapabilityAgentConstruct` (256 CPU, 512 MiB)
- Auto-registers in CloudMap `voice-agent-capabilities` namespace
- IAM permissions scoped to `bedrock:Retrieve` and `bedrock:RetrieveAndGenerate`
- Environment from SSM: `KB_KNOWLEDGE_BASE_ID`, `KB_RETRIEVAL_MAX_RESULTS`, `KB_MIN_CONFIDENCE_SCORE`

### Integration
- Voice agent discovers KB agent via `AgentRegistry` CloudMap polling
- Agent Card auto-generated with `search_knowledge_base` skill
- Filler phrases play during A2A calls (same UX as local tool)
- KB agent deploys independently without touching the voice agent

## Files Changed

```
backend/agents/knowledge-base-agent/main.py
backend/agents/knowledge-base-agent/Dockerfile
backend/agents/knowledge-base-agent/requirements.txt
infrastructure/src/stacks/kb-agent-stack.ts
```

## Dependencies

- `dynamic-capability-registry` (in progress) - AgentRegistry, A2A tool adapter, CloudMap namespace
- `knowledge-base-rag` (shipped) - Original KB service code that was ported
