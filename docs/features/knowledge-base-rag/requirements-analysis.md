# Knowledge Base Integration (RAG) - Requirements Analysis

**Document Version**: 1.0
**Date**: 2026-01-27
**Status**: Analysis Complete
**Analyst**: ProductVisionary

---

## Executive Summary

This analysis evaluates the requirements for integrating Retrieval-Augmented Generation (RAG) into the Pipecat voice agent using Amazon Bedrock Knowledge Bases. The feature would enable the voice agent to answer questions using company-specific documentation, grounding responses in authoritative sources.

**Recommendation**: Implement RAG as a **tool-based approach** (Option B) for the initial release, with inline context augmentation as a potential Phase 2 enhancement for high-frequency query patterns.

---

## 1. Requirements Gap Analysis

### 1.1 Gaps Identified in Original Idea

| Gap | Description | Recommendation |
|-----|-------------|----------------|
| **Integration Pattern Undefined** | Idea mentions both inline and tool-based approaches but does not commit | Clarify based on use case analysis (see Section 4) |
| **No Fallback Strategy** | What happens when knowledge base returns no relevant results? | Define graceful degradation behavior |
| **Citation Format Unspecified** | How should the agent cite sources in voice responses? | Natural language citations ("According to our return policy...") |
| **Document Update Workflow** | "Update without code deployment" needs process definition | S3 sync with scheduled ingestion jobs |
| **Chunk Size/Overlap** | No guidance on chunking strategy for voice context | Recommend 512 tokens, 50 token overlap for conversational retrieval |
| **Top-K Selection** | No retrieval count specified | Start with k=3, configurable via environment variable |
| **Session Context** | Should retrieved context persist across turns? | Yes, maintain retrieved context within conversation session |
| **Cost Monitoring** | No mention of retrieval cost tracking | Add CloudWatch metrics for retrieval invocations |

### 1.2 Clarifications Needed

1. **Document Corpus Scope**: What types of documents will be indexed initially? (FAQs, product docs, policies)
2. **Update Frequency**: How often will documents change? (Daily, weekly, monthly)
3. **Multi-Tenancy**: Will different callers need access to different knowledge bases?
4. **Sensitive Content**: Are there documents that should be excluded from certain contexts?

---

## 2. Acceptance Criteria

### 2.1 Infrastructure Criteria (MUST)

| ID | Criterion | Verification Method |
|----|-----------|---------------------|
| AC-1 | Bedrock Knowledge Base deployed with OpenSearch Serverless vector store | CDK output shows Knowledge Base ARN |
| AC-2 | S3 bucket created for document storage with proper IAM policies | AWS Console verification |
| AC-3 | Data source sync job runs successfully on first deployment | CloudWatch Logs show sync completion |
| AC-4 | ECS task role has `bedrock:Retrieve` permission for the knowledge base | IAM policy review |

### 2.2 Functional Criteria (MUST)

| ID | Criterion | Verification Method |
|----|-----------|---------------------|
| AC-5 | Voice agent can invoke knowledge base retrieval tool | End-to-end voice test with documentation query |
| AC-6 | Retrieved context is included in LLM prompt | CloudWatch Logs show augmented context |
| AC-7 | Agent responds with information from knowledge base, not hallucinated content | Manual verification with known Q&A pairs |
| AC-8 | Agent gracefully handles "no relevant results" scenario | Test query for non-existent topic |

### 2.3 Performance Criteria (MUST)

| ID | Criterion | Verification Method |
|----|-----------|---------------------|
| AC-9 | Knowledge base retrieval completes in < 500ms (p95) | CloudWatch custom metric |
| AC-10 | End-to-end latency with RAG < 2500ms | TimingObserver metrics |
| AC-11 | Retrieval does not block audio pipeline | No audio dropouts during retrieval |

### 2.4 Operational Criteria (SHOULD)

| ID | Criterion | Verification Method |
|----|-----------|---------------------|
| AC-12 | Documents can be added to S3 without code deployment | Upload test document, verify retrieval |
| AC-13 | Retrieval metrics visible in CloudWatch dashboard | Dashboard verification |
| AC-14 | Filler phrases play during retrieval when delay exceeds threshold | Audio test with slow network |

---

## 3. Effort Assessment

### 3.1 Component Breakdown

| Component | Effort | Complexity | Dependencies |
|-----------|--------|------------|--------------|
| **CDK: Knowledge Base Construct** | 2 days | Medium | OpenSearch Serverless, S3 |
| **CDK: IAM Permissions Update** | 0.5 days | Low | ECS stack |
| **Backend: KB Retrieval Tool** | 1 day | Low | Tool framework (exists) |
| **Backend: Context Augmentation** | 1 day | Medium | Pipeline integration |
| **Backend: Metrics Integration** | 0.5 days | Low | Observability framework (exists) |
| **Testing: Unit Tests** | 1 day | Low | Mocking boto3 |
| **Testing: Integration Tests** | 1 day | Medium | Live KB instance |
| **Documentation** | 0.5 days | Low | - |
| **Sample Documents** | 0.5 days | Low | - |

**Total Estimated Effort**: 8 days (1.5 developer-weeks)

### 3.2 Risk-Adjusted Estimate

| Factor | Adjustment |
|--------|------------|
| OpenSearch Serverless setup complexity | +1 day |
| Bedrock KB API learning curve | +0.5 days |
| Latency optimization iterations | +1 day |

**Risk-Adjusted Total**: 10.5 days (~2 developer-weeks)

### 3.3 Cost Estimate (Monthly)

| Resource | Estimated Cost | Notes |
|----------|----------------|-------|
| OpenSearch Serverless (2 OCU minimum) | ~$350/month | Collection + indexing |
| S3 Storage | < $1/month | For small document corpus |
| Bedrock KB Retrieval | ~$0.50 per 1000 queries | Negligible for POC |
| Data ingestion jobs | Included | Runs on sync |

**Total Infrastructure Cost**: ~$350/month (dominated by OpenSearch Serverless minimum)

---

## 4. Implementation Approach Recommendation

### 4.1 Option A: Inline Context Augmentation

**Description**: Every user query triggers a knowledge base retrieval before LLM inference.

```
User Speech -> STT -> KB Retrieval -> Context + Query -> LLM -> TTS -> Audio
```

**Pros**:
- Simple pipeline modification
- Always grounds responses in documentation
- No LLM decision-making overhead for retrieval

**Cons**:
- Adds 200-500ms latency to EVERY query
- Retrieves irrelevant context for non-documentation queries ("What time is it?")
- Higher cost from unnecessary retrievals
- Context window pollution with irrelevant chunks

**Use When**: High-percentage of queries require documentation (customer support hotline)

### 4.2 Option B: RAG as Tool (RECOMMENDED)

**Description**: LLM decides when to invoke knowledge base retrieval based on query nature.

```
User Speech -> STT -> LLM -> [decides to call kb_search tool] -> Retrieval -> LLM continues -> TTS -> Audio
```

**Pros**:
- LLM intelligently decides when retrieval is needed
- No latency penalty for simple queries
- Lower cost (only retrieves when necessary)
- Fits existing tool calling framework perfectly
- Filler phrase support already implemented for tool delays

**Cons**:
- Slightly more complex (but tool framework already exists)
- LLM might not always recognize when retrieval is needed
- Additional turn for retrieval response

**Use When**: Mixed query types (conversational + documentation)

### 4.3 Recommendation Rationale

**Recommend Option B (RAG as Tool)** for the following reasons:

1. **Existing Infrastructure**: Tool calling framework is already implemented and tested
2. **Filler Phrases**: `FunctionCallFillerProcessor` handles delays during tool execution
3. **Latency Budget**: Voice interactions require < 500ms for simple queries; inline RAG would push all queries to 700-1000ms
4. **Cost Efficiency**: Only pay for retrievals that are actually needed
5. **User Experience**: "Let me look that up for you..." is natural for documentation queries
6. **Flexibility**: Easy to add inline retrieval later for specific high-frequency patterns

### 4.4 Hybrid Approach (Phase 2)

For future optimization, consider a hybrid:
- **Tool-based** for general queries
- **Inline** for detected "FAQ patterns" using lightweight classification

---

## 5. Technical Architecture

### 5.1 Infrastructure Components

```
                                    +----------------------+
                                    |   S3 Bucket          |
                                    |   /documents/        |
                                    |   - faqs.md          |
                                    |   - policies.pdf     |
                                    |   - product-guide.docx|
                                    +----------+-----------+
                                               |
                                               | Sync Job
                                               v
+------------------+          +------------------+          +---------------------+
|  Pipecat ECS     |  Retrieve|  Bedrock         |  Query   |  OpenSearch         |
|  Container       +--------->+  Knowledge Base  +--------->+  Serverless         |
|                  |          |  (kb-voice-agent)|          |  (Vector Store)     |
|  kb_search tool  |<---------+                  |<---------+                     |
+------------------+  Chunks  +------------------+  Results +---------------------+
```

### 5.2 Data Flow

1. **Ingestion** (async, scheduled):
   - Documents uploaded to S3 bucket
   - Data source sync job triggered (manual or scheduled)
   - Documents chunked, embedded (Titan Embeddings), stored in OpenSearch

2. **Retrieval** (real-time, tool invocation):
   - LLM invokes `kb_search` tool with query
   - Tool calls `bedrock-agent-runtime:Retrieve` API
   - Top-k chunks returned with relevance scores
   - Context formatted and returned to LLM
   - LLM generates grounded response

### 5.3 Tool Definition

```python
kb_search_tool = ToolDefinition(
    name="search_knowledge_base",
    description=(
        "Search the company knowledge base for information about products, "
        "policies, procedures, and FAQs. Use this when the user asks about "
        "company-specific information, return policies, product features, "
        "troubleshooting steps, or any question that requires factual "
        "documentation to answer accurately."
    ),
    category=ToolCategory.KNOWLEDGE_BASE,
    parameters=[
        ToolParameter(
            name="query",
            type="string",
            description="The search query to find relevant documentation",
            required=True,
        ),
    ],
    executor=kb_search_executor,
    timeout_seconds=5.0,  # Allow for network latency
    requires_auth=False,
)
```

### 5.4 Response Format

Tool returns structured context for LLM consumption:

```json
{
  "results": [
    {
      "content": "Our return policy allows returns within 30 days...",
      "source": "policies/return-policy.md",
      "relevance_score": 0.92
    },
    {
      "content": "To initiate a return, visit our website or call...",
      "source": "faqs/returns.md",
      "relevance_score": 0.87
    }
  ],
  "result_count": 2,
  "query_time_ms": 245
}
```

---

## 6. Dependencies

### 6.1 Upstream Dependencies

| Dependency | Status | Risk |
|------------|--------|------|
| Tool Calling Framework | Shipped | None |
| Filler Phrase Processor | Shipped | None |
| Bedrock IAM Permissions | Exists (needs extension) | Low |
| CloudWatch Metrics | Exists | None |

### 6.2 Infrastructure Dependencies

| Dependency | Status | Provisioning |
|------------|--------|--------------|
| OpenSearch Serverless Collection | New | CDK construct |
| S3 Bucket for Documents | New | CDK construct |
| Bedrock Knowledge Base | New | CDK construct |
| VPC Endpoint for OpenSearch | May need | CDK update |

### 6.3 External Dependencies

| Dependency | Status | Notes |
|------------|--------|-------|
| Bedrock KB Feature Availability | GA | Available in us-east-1 |
| Titan Embeddings Model Access | Requires enablement | Bedrock model access request |
| OpenSearch Serverless Quota | Check | May need quota increase |

---

## 7. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| OpenSearch Serverless cold start adds latency | Medium | Medium | Keep collection warm with periodic queries; set minimum OCU |
| Retrieved context irrelevant to query | Medium | Medium | Tune relevance threshold; add LLM post-filtering |
| Document sync fails silently | Low | High | CloudWatch alarms on sync job status |
| Context window overflow with large retrievals | Low | Medium | Limit to 3 chunks, 512 tokens each |
| Cost higher than expected | Low | Low | Monitor retrieval metrics; set budget alarms |
| Latency exceeds 500ms target | Medium | High | Cache frequent queries; optimize chunk size |

---

## 8. Success Metrics

### 8.1 Primary Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Retrieval Latency (p95) | < 500ms | CloudWatch custom metric |
| Retrieval Relevance | > 80% useful | Manual sampling |
| E2E Latency with RAG | < 2500ms | TimingObserver |
| Tool Invocation Rate | N/A (baseline) | CloudWatch |

### 8.2 Observability Additions

```yaml
New CloudWatch Metrics:
  - VoiceAgent/Pipeline/KBRetrievalLatency (ms)
  - VoiceAgent/Pipeline/KBRetrievalCount (count)
  - VoiceAgent/Pipeline/KBResultCount (count)
  - VoiceAgent/Pipeline/KBRelevanceScore (average)

New Dashboard Widgets:
  - KB Retrieval Latency (line chart)
  - KB Invocations per Hour (bar chart)
  - KB Results Distribution (histogram)
```

---

## 9. Implementation Phases

### Phase 1: Infrastructure (3 days)
- [ ] Create CDK construct for Bedrock Knowledge Base
- [ ] Create S3 bucket for document storage
- [ ] Configure OpenSearch Serverless collection
- [ ] Update ECS task role with `bedrock:Retrieve` permission
- [ ] Deploy and verify infrastructure

### Phase 2: Backend Integration (3 days)
- [ ] Implement `kb_search` tool using existing tool framework
- [ ] Create boto3 client wrapper for bedrock-agent-runtime
- [ ] Add tool to pipeline registration
- [ ] Update filler phrases for KB search
- [ ] Add CloudWatch metrics for retrieval

### Phase 3: Testing & Optimization (3 days)
- [ ] Unit tests with mocked Bedrock client
- [ ] Integration tests with live knowledge base
- [ ] Sample document corpus creation
- [ ] Latency optimization (caching, chunk tuning)
- [ ] End-to-end voice testing

### Phase 4: Documentation & Rollout (1 day)
- [ ] Update CLAUDE.md with new environment variables
- [ ] Document knowledge base management procedures
- [ ] Create runbook for document updates

---

## 10. Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_KNOWLEDGE_BASE` | `false` | Enable KB search tool |
| `KNOWLEDGE_BASE_ID` | - | Bedrock Knowledge Base ID |
| `KB_RETRIEVAL_TOP_K` | `3` | Number of chunks to retrieve |
| `KB_RELEVANCE_THRESHOLD` | `0.7` | Minimum relevance score |
| `KB_MAX_CONTEXT_TOKENS` | `1500` | Maximum tokens from KB in context |

---

## 11. Open Questions (For Stakeholder Input)

1. **Document Corpus**: What documents should be included in the initial knowledge base?
2. **Update Cadence**: How often will documents be updated? (Affects sync job scheduling)
3. **Multi-KB Support**: Will different use cases need separate knowledge bases?
4. **Citation Preference**: Should the agent explicitly cite sources in responses?
5. **Fallback Behavior**: When KB returns no results, should the agent say so or try to answer anyway?

---

## 12. Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-01-27 | RAG as Tool (not inline) | Preserves latency for simple queries; leverages existing tool framework |
| 2026-01-27 | OpenSearch Serverless over Aurora pgvector | Native Bedrock KB integration; managed scaling |
| 2026-01-27 | Titan Embeddings over Cohere | Native AWS; no additional licensing |

---

## 13. References

- [Amazon Bedrock Knowledge Bases API Reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_Retrieve.html)
- [Retrieve and Generate Documentation](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html)
- [Boto3 Retrieve API](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-agent-runtime/client/retrieve_and_generate.html)
- [AWS Bedrock Knowledge Bases Overview](https://aws.amazon.com/bedrock/knowledge-bases/)

---

**Document Status**: Ready for stakeholder review

**Next Steps**:
1. Stakeholder review and approval of approach
2. Answer open questions (Section 11)
3. Create `plan.md` with detailed implementation tasks
4. Begin Phase 1 implementation
