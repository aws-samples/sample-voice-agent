---
id: context-awareness-service
name: Context Awareness Service
type: Feature
priority: P2
effort: Medium
impact: Medium
created: 2026-02-02
---

# Context Awareness Service

## Problem Statement

The voice agent treats each call as an isolated interaction, lacking awareness of:
- Previous calls from the same customer
- Recent account activity or changes
- Ongoing issues or open tickets
- Customer preferences and history

This leads to repetitive conversations and missed opportunities to proactively address issues.

## Proposed Solution

Build a context awareness layer that aggregates customer data from multiple sources before and during the call, enriching the conversation with relevant background information.

### Context Sources

```
┌─────────────────────────────────────────────────────────────┐
│                 Context Awareness Service                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   Previous   │  │   Account    │  │   Recent     │       │
│  │    Calls     │  │   Activity   │  │   Tickets    │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                  │                  │              │
│  ┌──────▼───────┐  ┌──────▼───────┐  ┌──────▼───────┐       │
│  │   DynamoDB   │  │     CRM      │  │   Support    │       │
│  │   Sessions   │  │     API      │  │   System     │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                  │                  │              │
│         └──────────────────┼──────────────────┘              │
│                            │                                 │
│                   ┌────────▼────────┐                        │
│                   │  Context        │                        │
│                   │  Aggregator     │                        │
│                   │  & Enricher     │                        │
│                   └────────┬────────┘                        │
│                            │                                 │
│                   ┌────────▼────────┐                        │
│                   │  LLM Context    │                        │
│                   │  Injection      │                        │
│                   └─────────────────┘                        │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Context Types

#### 1. Call History Context
- Total calls in last 30 days
- Last call date and topic
- Resolution status
- Frequent issues

#### 2. Account Activity Context
- Recent orders
- Recent payments
- Account changes
- Service outages

#### 3. Open Issues Context
- Current open tickets
- Escalated issues
- Pending customer actions

### Technical Design

```python
# app/services/context_awareness_service.py

class ContextAwarenessService:
    """Aggregates and enriches customer context from multiple sources."""
    
    def __init__(self):
        self.session_tracker = SessionTracker()
        self.crm_service = CRMServiceFactory.get_crm_service()
    
    async def build_customer_context(
        self,
        customer_id: str,
        phone_number: str,
    ) -> CustomerContext:
        """Build comprehensive context for a customer."""
        # Fetch all context in parallel for speed
        results = await asyncio.gather(
            self._get_call_history(phone_number),
            self._get_account_activity(customer_id),
            self._get_open_issues(customer_id),
            return_exceptions=True,
        )
        
        return CustomerContext(
            call_history=results[0],
            account_activity=results[1],
            open_issues=results[2],
        )
    
    def enrich_system_prompt(
        self,
        base_prompt: str,
        context: CustomerContext,
    ) -> str:
        """Enrich the system prompt with customer context."""
        # Inject context into LLM system prompt
        pass
```

## Acceptance Criteria

- [ ] Automatically retrieves call history from session tracking
- [ ] Fetches recent account activity from CRM
- [ ] Identifies open tickets and ongoing issues
- [ ] Enriches system prompt with relevant context
- [ ] Context retrieval completes in < 2 seconds
- [ ] Graceful handling if context sources are unavailable
- [ ] Configurable context sources (enable/disable per source)
- [ ] Privacy-compliant (only fetch data for authenticated customers)

## Dependencies

- Session tracking (existing DynamoDB)
- CRM Integration Tool
- Support ticket system integration
- Tool calling framework
