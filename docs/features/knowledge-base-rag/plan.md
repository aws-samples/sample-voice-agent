---
started: 2026-01-27
---

# Implementation Plan: Knowledge Base Integration (RAG)

## Overview

Add Retrieval-Augmented Generation (RAG) to the voice agent using Amazon Bedrock Knowledge Bases. The LLM will have access to a `search_knowledge_base` tool that retrieves relevant documentation chunks, enabling grounded responses with company-specific information.

**Key Decision:** Implement RAG as a **tool** (not inline context) so the LLM decides when to search, avoiding latency on simple queries and leveraging the existing filler phrase system.

## Architecture Summary

```
User Speech → STT → LLM (decides to search) → KB Tool → Bedrock KB →
S3 Vectors Vector Search → Retrieved Chunks → LLM synthesizes → TTS → Audio
```

**Components:**
- **Infrastructure:** S3 bucket + Bedrock Knowledge Base + S3 Vectors (~100x cheaper than OpenSearch)
- **Backend:** `KnowledgeBaseService` + `search_knowledge_base` tool
- **Integration:** Tool registered in pipeline, KB ID from SSM parameter
- **Deployment:** Standalone KnowledgeBaseStack + ECS Stack (reads from SSM)

## Implementation Steps

### Phase 1: Infrastructure (CDK)

- [x] Step 1: Add SSM parameter constants for Knowledge Base
  - File: `infrastructure/src/ssm-parameters.ts`
  - Add: `KNOWLEDGE_BASE_ID`, `KNOWLEDGE_BASE_ARN`, `KNOWLEDGE_BASE_BUCKET`, `KNOWLEDGE_BASE_DATA_SOURCE_ID`

- [x] Step 2: Create KnowledgeBaseConstruct
  - File: `infrastructure/src/constructs/knowledge-base-construct.ts`
  - Creates: S3 bucket, S3 Vectors vector store, Bedrock Knowledge Base, S3 data source
  - Includes: IAM service role, custom resource Lambda for lifecycle management, SSM outputs
  - Exposes: `knowledgeBaseId`, `knowledgeBaseArn`, `documentBucket`

- [x] Step 3: Export construct from index
  - File: `infrastructure/src/constructs/index.ts`
  - Add export for `KnowledgeBaseConstruct`

- [x] Step 4: Create KnowledgeBaseStack
  - File: `infrastructure/src/stacks/knowledge-base-stack.ts`
  - Standalone stack for Knowledge Base resources
  - Can be deployed independently before ECS

- [x] Step 5: Integrate with ECS stack
  - File: `infrastructure/src/stacks/ecs-stack.ts`
  - Add KB query permissions to task role
  - Read `KB_KNOWLEDGE_BASE_ID` from SSM parameter

- [x] Step 6: Update CDK app entry point
  - File: `infrastructure/src/main.ts`
  - Add KnowledgeBaseStack to deployment with proper dependencies

### Phase 2: Backend Service

- [x] Step 7: Create KnowledgeBaseService
  - File: `backend/voice-agent/app/services/knowledge_base_service.py`
  - Async boto3 bedrock-agent-runtime client
  - `retrieve()` method with configurable top-k
  - Result parsing with confidence filtering
  - Connection pooling for low latency

- [x] Step 8: Create knowledge_base_tool
  - File: `backend/voice-agent/app/tools/builtin/knowledge_base_tool.py`
  - Tool schema with `query` and optional `max_results` parameters
  - Executor function with graceful error handling
  - Voice-optimized result formatting

- [x] Step 9: Register tool in pipeline
  - File: `backend/voice-agent/app/tools/builtin/__init__.py`
  - Export `knowledge_base_tool`
  - File: `backend/voice-agent/app/pipeline_ecs.py`
  - Conditionally register tool when `KB_KNOWLEDGE_BASE_ID` is set

- [x] Step 10: Update system prompt for RAG
  - File: `backend/voice-agent/app/pipeline_ecs.py`
  - Add instructions for synthesizing KB results naturally
  - Citation guidance: "According to our [source]..."

### Phase 3: Testing

- [x] Step 11: Unit tests for KnowledgeBaseService
  - File: `backend/voice-agent/tests/test_knowledge_base_service.py`
  - Mock boto3 client responses
  - Test result parsing, filtering, error handling

- [x] Step 12: Unit tests for knowledge_base_tool
  - File: `backend/voice-agent/tests/test_knowledge_base_tool.py`
  - Test tool schema validation
  - Test executor with mocked service
  - Test error responses (no results, unavailable, invalid query)

- [ ] Step 13: CDK tests for KnowledgeBaseConstruct
  - File: `infrastructure/test/knowledge-base.test.ts`
  - Snapshot tests for construct resources
  - Verify IAM permissions are correct

- [x] Step 14: Integration test with sample documents
  - Upload sample documents to S3
  - Documents auto-sync via data source
  - Verified retrieval returns expected results

### Phase 4: Documentation & Deployment

- [x] Step 15: Add sample documents
  - File: `resources/knowledge-base-documents/sample-faq.md`
  - Sample FAQ with company policies and product information
  - Auto-uploaded via CDK BucketDeployment

- [x] Step 16: Update CLAUDE.md with KB environment variables
  - Added: `KB_KNOWLEDGE_BASE_ID`, `KB_RETRIEVAL_MAX_RESULTS`, `KB_MIN_CONFIDENCE_SCORE`

- [x] Step 17: Deploy and validate
  - Deployed KnowledgeBaseStack (standalone)
  - Documents auto-synced via data source
  - Deployed ECS with KB integration (reads from SSM)
  - ECS service running with correct KB_ID: OJDL2XJKEJ

## Technical Decisions

### RAG as Tool vs. Inline Context
**Decision:** Tool-based approach
**Rationale:**
- Existing tool framework handles execution, timeouts, cancellation
- Filler phrases ("Let me look that up...") provide natural UX during retrieval
- LLM decides when KB search is needed, avoiding latency on simple queries
- Cost-efficient: only pay for retrievals that are actually needed

### Vector Store Selection
**Decision:** S3 Vectors (not OpenSearch Serverless)
**Rationale:**
- ~100x cheaper than OpenSearch Serverless (no minimum OCU charges)
- Native AWS integration with Bedrock Knowledge Bases
- Sufficient performance for voice agent RAG use case
- Managed by AWS, no operational overhead
**Trade-off:** Slightly higher latency than OpenSearch for very large datasets

### Embedding Model
**Decision:** Amazon Titan Embeddings V2 (`amazon.titan-embed-text-v2:0`)
**Rationale:**
- Low latency, cost-effective
- 1024 dimensions, good quality for RAG
- Native Bedrock integration

### Chunking Strategy
**Decision:** Fixed-size chunking (512 tokens, ~12% overlap)
**Rationale:**
- Simple, predictable behavior
- 512 tokens fits well in voice context (concise responses)
- Overlap preserves context at chunk boundaries

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `KB_KNOWLEDGE_BASE_ID` | *required* | Bedrock Knowledge Base ID |
| `KB_RETRIEVAL_MAX_RESULTS` | `3` | Default number of chunks to retrieve |
| `KB_MIN_CONFIDENCE_SCORE` | `0.3` | Filter results below this score |

## Testing Strategy

1. **Unit Tests:** Mock boto3 responses, test service/tool logic
2. **CDK Tests:** Snapshot tests for infrastructure
3. **Integration Tests:** Real KB queries with sample documents
4. **E2E Voice Tests:** Verify natural voice responses with citations

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| OpenSearch Serverless cold start | First query slow (2-3s) | Keep-alive queries or accept cold start |
| High infrastructure cost | ~$700/month minimum | Make KB optional, document cost |
| Irrelevant results returned | Poor user experience | Tune confidence threshold, improve prompts |
| Sync job failures | Stale knowledge | CloudWatch alarms on sync status |
| Latency exceeds target | Degraded voice UX | Connection pooling, timeout handling |

## Success Criteria

- [x] Knowledge base infrastructure deploys successfully (standalone stack)
- [x] Documents sync from S3 automatically via data source
- [x] ECS service reads KB_ID from SSM parameter
- [ ] Retrieval latency < 500ms p95 (to be validated)
- [ ] Voice agent cites sources naturally in responses (to be validated)
- [x] Filler phrases play during KB retrieval when delay > 1.5s (existing system)
- [x] Graceful degradation when KB returns no results (implemented in tool)

## Dependencies

- Bedrock Knowledge Bases available in deployment region
- OpenSearch Serverless quotas sufficient
- Existing tool calling framework (completed)
- Filler phrase system (completed)

## Estimated Effort

| Phase | Effort |
|-------|--------|
| Infrastructure (Steps 1-6) | 2 days |
| Backend Service (Steps 7-10) | 1.5 days |
| Testing (Steps 11-14) | 2 days |
| Documentation & Deployment (Steps 15-17) | 1 day |
| **Total** | **~6.5 days** |

Buffer for OpenSearch complexity and integration issues: +1.5 days
**Risk-adjusted total:** ~8 days (1.5 weeks)
