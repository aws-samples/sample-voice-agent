---
id: smart-transfer-tool
name: Smart Transfer Tool
type: Feature
priority: P2
effort: Medium
impact: High
created: 2026-02-02
---

# Smart Transfer Tool

## Problem Statement

When transferring calls to human agents, critical context is often lost. Agents must ask customers to repeat information, causing frustration and longer handle times. The current transfer tool lacks intelligent context handoff capabilities.

## Proposed Solution

Create a smart transfer tool that:
- Packages full conversation context for the receiving agent
- Routes to the optimal queue/agent based on intent and skills
- Passes context via SIP headers or webhooks
- Supports both cold transfers (SIP REFER) and warm handoffs

### Transfer Methods

#### 1. SIP REFER (Cold Transfer)

Daily.co completely exits the call. Customer connects directly to external CCaaS.

```python
async def sip_refer_transfer(
    self,
    session_id: str,
    destination: str,  # SIP URI
    context: TransferContext,
) -> TransferResult:
    """
    Transfer call via SIP REFER.
    
    Daily exits call path - customer connects directly to external system.
    Context passed via SIP headers.
    """
    # Build SIP headers with context
    sip_headers = {
        "X-AI-Session-ID": session_id,
        "X-AI-Intent": context.intent,
        "X-AI-Priority": context.priority,
        "X-AI-Sentiment": context.sentiment,
        "X-AI-Context-URL": f"{self.config.context_api_url}/context/{session_id}",
    }
    
    # Execute SIP REFER via Daily API
    result = await self.daily_client.sip_refer(
        room_name=context.room_name,
        session_id=session_id,
        sip_uri=destination,
        headers=sip_headers,
    )
    
    # Store full context for agent retrieval
    await self._store_transfer_context(session_id, context)
    
    return TransferResult(
        success=True,
        method="sip_refer",
        destination=destination,
        context_url=sip_headers["X-AI-Context-URL"],
    )
```

#### 2. Warm Handoff (Daily Anchored)

Daily remains in call. AI introduces customer to human agent before dropping off.

```python
async def warm_handoff_transfer(
    self,
    session_id: str,
    destination: str,
    context: TransferContext,
) -> TransferResult:
    """
    Warm handoff with AI introduction.
    
    1. AI introduces customer to agent
    2. 3-way conference briefly
    3. AI drops off
    """
    # Step 1: Add human agent to call
    await self.daily_client.sip_call_transfer(
        room_name=context.room_name,
        session_id=session_id,
        to_endpoint=destination,
    )
    
    # Step 2: AI provides context to agent
    intro_message = self._build_agent_intro(context)
    await self._send_agent_message(intro_message)
    
    # Step 3: AI says goodbye to customer
    await self._say_goodbye(context)
    
    # Step 4: AI drops from call
    await self.daily_client.leave_room(context.room_name)
    
    return TransferResult(
        success=True,
        method="warm_handoff",
        destination=destination,
    )
```

### Context Package

```python
@dataclass
class TransferContext:
    """Complete context package for human agent."""
    
    # Call metadata
    session_id: str
    room_name: str
    start_time: datetime
    duration_seconds: int
    
    # Customer info
    customer_id: str
    customer_name: str
    customer_phone: str
    account_type: str
    
    # Conversation summary
    transcript: str
    turn_count: int
    detected_intent: str
    intent_confidence: float
    
    # AI analysis
    sentiment_analysis: Dict
    issue_summary: str
    suggested_resolution: str
    
    # Actions taken
    authentication_level: str
    tools_used: List[str]
    data_accessed: List[str]
    
    # Transfer reason
    transfer_reason: str
    priority: str
    
    # Recommended actions
    recommended_queue: str
    suggested_agent_skills: List[str]
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "session_id": self.session_id,
            "duration_seconds": self.duration_seconds,
            "customer": {
                "id": self.customer_id,
                "name": self.customer_name,
                "phone": self.customer_phone,
                "account_type": self.account_type,
            },
            "conversation": {
                "turn_count": self.turn_count,
                "intent": self.detected_intent,
                "intent_confidence": self.intent_confidence,
                "transcript": self.transcript,
            },
            "analysis": {
                "sentiment": self.sentiment_analysis,
                "issue_summary": self.issue_summary,
                "suggested_resolution": self.suggested_resolution,
            },
            "transfer": {
                "reason": self.transfer_reason,
                "priority": self.priority,
                "recommended_queue": self.recommended_queue,
                "suggested_skills": self.suggested_agent_skills,
            },
        }
```

### Smart Routing

```python
async def select_optimal_destination(
    self,
    context: TransferContext,
) -> str:
    """
    Select best transfer destination based on context.
    
    Considers:
    - Intent-based routing
    - Agent skills matching
    - Queue depth/wait times
    - Customer priority
    """
    # Get queue metrics from CCaaS
    queues = await self.ccaas_client.get_queue_metrics()
    
    # Intent-based routing
    intent_queue_map = {
        "billing_inquiry": "billing_queue",
        "technical": "tech_support_queue",
        "order": "order_support_queue",
    }
    
    primary_queue = intent_queue_map.get(
        context.detected_intent, 
        "general_queue"
    )
    
    # Check if primary queue has acceptable wait time
    primary_metrics = queues.get(primary_queue)
    if primary_metrics and primary_metrics.estimated_wait_minutes < 5:
        return primary_metrics.sip_uri
    
    # Check overflow queues
    overflow_queues = self.overflow_map.get(primary_queue, [])
    for queue_name in overflow_queues:
        metrics = queues.get(queue_name)
        if metrics and metrics.estimated_wait_minutes < 3:
            return metrics.sip_uri
    
    # Fall back to primary with wait time warning
    return primary_metrics.sip_uri
```

### Agent Screen Pop

```python
# Context API for agent screen pop

from fastapi import FastAPI, HTTPException

app = FastAPI()

@app.get("/context/{session_id}")
async def get_transfer_context(session_id: str):
    """
    Retrieve full context for transferred call.
    
    Called by CCaaS agent desktop to populate screen pop.
    """
    context = await context_store.get(session_id)
    
    if not context:
        raise HTTPException(status_code=404, detail="Context not found")
    
    return {
        "customer": context.customer,
        "conversation_summary": context.issue_summary,
        "transcript": context.transcript,
        "sentiment": context.sentiment_analysis,
        "actions_taken": context.tools_used,
        "suggested_resolution": context.suggested_resolution,
        "transfer_reason": context.transfer_reason,
    }
```

### Conversation Flow Example

```
[Customer has been on call for 8 minutes with unresolved billing issue]

AI: "I understand this is frustrating, and I want to make sure you get this 
     resolved properly. Let me connect you with a billing specialist who can 
     review your account in detail. I'll make sure they have all the information 
     so you won't need to repeat yourself."

[Tool Call: smart_transfer with context]

[AI gathers complete context: transcript, sentiment, authentication level, 
 tools used, issue summary, suggested resolution]

[SIP REFER initiated to billing queue with headers]

[Customer transferred to human agent]

Agent Screen Pop:
╔════════════════════════════════════════════════════════════════╗
║  TRANSFERRED CALL - AI CONVERSATION SUMMARY                    ║
╠════════════════════════════════════════════════════════════════╣
║  Customer: John Smith (Premium Member)                         ║
║  Phone: 555-123-4567                                           ║
║  Call Duration: 8 minutes                                      ║
║  Transferred: Frustrated customer, unresolved billing dispute  ║
╠════════════════════════════════════════════════════════════════╣
║  ISSUE SUMMARY:                                                ║
║  Customer disputing $247 charge from October. Claims duplicate ║
║  of September payment. AI verified account, confirmed charge.  ║
║  Customer escalated when AI couldn't process refund.           ║
╠════════════════════════════════════════════════════════════════╣
║  AUTHENTICATION: High (verified identity)                      ║
║  SENTIMENT: Frustrated (0.8/1.0), declining trend              ║
║  ACCOUNT STATUS: Premium, member since 2019                    ║
╠════════════════════════════════════════════════════════════════╣
║  SUGGESTED RESOLUTION:                                         ║
║  Review transaction history. If duplicate confirmed, process   ║
║  refund per policy 4.2.1. Consider goodwill credit for         ║
║  inconvenience.                                                ║
╠════════════════════════════════════════════════════════════════╣
║  [View Full Transcript]  [Open Account]  [Process Refund]      ║
╚════════════════════════════════════════════════════════════════╝

Agent: "Hi John, this is Sarah from billing. I can see you've been dealing 
        with a charge dispute, and I have all the details here. Let me pull 
        up your transaction history and get this sorted out for you right away."
```

## Acceptance Criteria

- [ ] Packages full conversation context for transfer
- [ ] Routes to optimal queue based on intent and skills
- [ ] Passes context via SIP headers
- [ ] Provides context API for agent screen pop
- [ ] Supports SIP REFER (cold transfer)
- [ ] Supports warm handoff (AI introduction)
- [ ] Considers queue depth and wait times
- [ ] Includes sentiment and priority in routing
- [ ] Context available for at least 24 hours post-transfer

## Dependencies

- Intent Classification Service
- Sentiment Analysis Processor
- Context Awareness Service
- Daily.co SIP transfer capabilities
- CCaaS integration (Genesys, etc.)

## Notes

- Context should be comprehensive but concise for agents
- Include AI confidence levels for recommendations
- Support different context formats for different CCaaS platforms
- Consider privacy when storing conversation transcripts
