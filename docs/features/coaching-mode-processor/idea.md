---
id: coaching-mode-processor
name: Coaching Mode Processor
type: Feature
priority: P3
effort: Large
impact: Medium
created: 2026-02-02
---

# Coaching Mode Processor

## Problem Statement

Human agents sometimes struggle with complex calls or unfamiliar situations. An AI coaching mode could provide real-time guidance to agents, suggesting responses, highlighting key information, and helping navigate difficult conversations - all without the customer hearing.

## Proposed Solution

Implement a "whisper" coaching mode where the AI listens to the conversation between customer and human agent, then provides real-time suggestions and guidance to the agent via a separate channel (text interface, headset audio, or dashboard).

### Coaching Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    COACHING MODE ARCHITECTURE                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   Customer                    Human Agent                    AI Coach    │
│      │                             │                            │       │
│      │  Audio                      │  Audio                     │       │
│      │                             │                            │       │
│      └──────────────┬──────────────┘                            │       │
│                     │                                           │       │
│                     ▼                                           │       │
│            ┌─────────────────┐                                  │       │
│            │   Daily Room    │                                  │       │
│            │  (3-way call)   │                                  │       │
│            └────────┬────────┘                                  │       │
│                     │                                           │       │
│        ┌────────────┼────────────┐                              │       │
│        │            │            │                              │       │
│        ▼            ▼            ▼                              ▼       │
│   ┌─────────┐  ┌─────────┐  ┌──────────┐              ┌──────────────┐ │
│   │  STT    │  │  STT    │  │  Coach   │              │  Coaching    │ │
│   │Customer │  │  Agent  │  │  Audio   │              │  Engine      │ │
│   └────┬────┘  └────┬────┘  └────┬─────┘              └──────┬───────┘ │
│        │            │            │                            │         │
│        └────────────┴────────────┘                            │         │
│                     │                                         │         │
│                     ▼                                         ▼         │
│            ┌─────────────────┐                      ┌─────────────────┐ │
│            │  Conversation   │─────────────────────►│  Real-time      │ │
│            │  Analysis       │                      │  Guidance       │ │
│            └─────────────────┘                      └────────┬────────┘ │
│                                                              │          │
│                                                              ▼          │
│                                                     ┌─────────────────┐ │
│                                                     │  Agent Dashboard│ │
│                                                     │  - Suggestions  │ │
│                                                     │  - Key Info     │ │
│                                                     │  - Alerts       │ │
│                                                     └─────────────────┘ │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Coaching Capabilities

```python
@dataclass
class CoachingSuggestion:
    """Real-time coaching suggestion for agent."""
    
    type: str  # "response", "info", "alert", "reminder"
    priority: str  # "low", "medium", "high", "urgent"
    message: str
    context: str  # Why this suggestion is relevant
    suggested_action: Optional[str]
    auto_display: bool  # Show immediately or on-demand

class CoachingEngine:
    """AI coaching engine for human agents."""
    
    def __init__(self):
        self.llm = BedrockLLMService()
        self.knowledge_base = KnowledgeBaseService()
        self.customer_context = None
    
    async def analyze_conversation(
        self,
        customer_transcript: str,
        agent_transcript: str,
        conversation_history: List[Dict],
    ) -> List[CoachingSuggestion]:
        """
        Analyze conversation and generate coaching suggestions.
        
        Runs continuously in background during human-agent call.
        """
        suggestions = []
        
        # 1. Detect customer intent and emotion
        intent = await self._detect_intent(customer_transcript)
        sentiment = await self._analyze_sentiment(customer_transcript)
        
        # 2. Check if agent response is optimal
        agent_response_quality = await self._evaluate_agent_response(
            agent_transcript, customer_transcript, intent
        )
        
        if agent_response_quality.score < 0.6:
            suggestions.append(CoachingSuggestion(
                type="response",
                priority="medium",
                message=agent_response_quality.suggested_improvement,
                context="Customer may not have understood",
                suggested_action=agent_response_quality.better_response,
                auto_display=True,
            ))
        
        # 3. Surface relevant knowledge base articles
        if intent.confidence > 0.7:
            kb_articles = await self.knowledge_base.search(
                query=intent.description,
                max_results=2,
            )
            for article in kb_articles:
                suggestions.append(CoachingSuggestion(
                    type="info",
                    priority="low",
                    message=article.title,
                    context=f"Relevant to: {intent.description}",
                    suggested_action=f"Open KB article: {article.url}",
                    auto_display=False,
                ))
        
        # 4. Alert on escalation triggers
        if sentiment.frustration > 0.8:
            suggestions.append(CoachingSuggestion(
                type="alert",
                priority="high",
                message="Customer showing high frustration",
                context="Consider escalation or supervisor assistance",
                suggested_action="Offer to escalate to supervisor",
                auto_display=True,
            ))
        
        # 5. Remind about key information
        if self.customer_context:
            reminders = self._generate_reminders(customer_transcript)
            suggestions.extend(reminders)
        
        return suggestions
    
    async def _evaluate_agent_response(
        self,
        agent_text: str,
        customer_text: str,
        intent: IntentClassification,
    ) -> ResponseQuality:
        """Evaluate quality of agent's response."""
        
        prompt = f"""
        Evaluate this agent response to a customer.
        
        Customer said: "{customer_text}"
        Intent: {intent.intent} (confidence: {intent.confidence})
        
        Agent responded: "{agent_text}"
        
        Rate the response:
        1. Did it address the customer's concern? (0-1)
        2. Was it clear and professional? (0-1)
        3. Could it be improved?
        
        If score < 0.6, suggest a better response.
        
        Return JSON:
        {{
            "score": 0.0-1.0,
            "suggested_improvement": "...",
            "better_response": "..."
        }}
        """
        
        result = await self.llm.generate(prompt)
        return ResponseQuality(**json.loads(result))
    
    def _generate_reminders(self, customer_text: str) -> List[CoachingSuggestion]:
        """Generate contextual reminders based on customer data."""
        reminders = []
        
        # Check for missed opportunities
        if "discount" in customer_text.lower() and not self.discount_offered:
            reminders.append(CoachingSuggestion(
                type="reminder",
                priority="medium",
                message="Customer mentioned discount - eligibility available",
                context="Customer qualifies for 10% loyalty discount",
                suggested_action="Offer discount code LOYAL10",
                auto_display=True,
            ))
        
        # Remind about open issues
        if self.customer_context.open_issues:
            for issue in self.customer_context.open_issues[:2]:
                reminders.append(CoachingSuggestion(
                    type="reminder",
                    priority="low",
                    message=f"Open issue: {issue.subject}",
                    context=f"Ticket #{issue.id} - {issue.status}",
                    suggested_action="Reference during call",
                    auto_display=False,
                ))
        
        return reminders
```

### Agent Dashboard

```python
# WebSocket-based coaching dashboard

class CoachingDashboard:
    """Real-time coaching interface for agents."""
    
    async def display_suggestion(self, suggestion: CoachingSuggestion):
        """Display suggestion to agent."""
        
        if suggestion.type == "response":
            await self.websocket.send_json({
                "type": "suggested_response",
                "priority": suggestion.priority,
                "message": suggestion.message,
                "suggested_action": suggestion.suggested_action,
                "display_style": "banner" if suggestion.priority == "high" else "sidebar",
            })
        
        elif suggestion.type == "info":
            await self.websocket.send_json({
                "type": "knowledge_card",
                "title": suggestion.message,
                "context": suggestion.context,
                "action": suggestion.suggested_action,
            })
        
        elif suggestion.type == "alert":
            await self.websocket.send_json({
                "type": "alert",
                "priority": suggestion.priority,
                "message": suggestion.message,
                "context": suggestion.context,
                "action": suggestion.suggested_action,
            })
```

### Coaching Modes

#### Mode 1: Whisper (Audio)
AI speaks directly to agent via separate audio channel (muted to customer)

```python
async def whisper_to_agent(self, message: str):
    """Send audio coaching to agent only."""
    # Generate TTS
    audio = await self.tts_service.synthesize(message)
    
    # Send to agent's audio channel only
    await self.daily_client.send_audio_to_participant(
        participant_id=self.agent_participant_id,
        audio=audio,
    )
```

#### Mode 2: Visual Dashboard
Text-based suggestions in agent desktop application

#### Mode 3: Hybrid
Audio alerts for urgent items, visual for reference material

### Use Cases

**1. New Agent Training**
- Real-time guidance on responses
- Reminders about procedures
- Suggested next steps

**2. Complex Issues**
- Surface relevant knowledge base articles
- Suggest escalation paths
- Highlight policy requirements

**3. Difficult Customers**
- Sentiment alerts
- De-escalation suggestions
- Supervisor notification triggers

**4. Sales Opportunities**
- Upsell suggestions
- Cross-sell reminders
- Promotion alerts

### Conversation Example

```
[Customer on call with human agent]

Customer: "I've been waiting 3 weeks for my refund and still haven't seen it!"

[AI Coaching Engine analyzes in real-time]

[Dashboard Alert - HIGH PRIORITY]
╔════════════════════════════════════════════════════════════╗
║  ⚠️ CUSTOMER FRUSTRATION DETECTED                          ║
╠════════════════════════════════════════════════════════════╣
║  Customer sentiment: Angry (0.9/1.0)                       ║
║  Issue: Refund delay - 3 weeks                             ║
╠════════════════════════════════════════════════════════════╣
║  SUGGESTED RESPONSE:                                       ║
║  "I sincerely apologize for the delay. That's completely   ║
║   unacceptable. Let me check the status right now and      ║
║   escalate this for immediate processing."                 ║
╠════════════════════════════════════════════════════════════╣
║  [KB Article: Refund Processing Delays]                    ║
║  [Escalate to Supervisor]                                  ║
╚════════════════════════════════════════════════════════════╝

[Agent sees alert and adjusts response]

Agent: "I sincerely apologize for the delay. That's completely unacceptable. 
        Let me check the status right now and escalate this for immediate 
        processing. I can see you've been waiting far too long."

Customer: "Thank you, I appreciate that"

[Sentiment improves to neutral]

[Dashboard Update]
╔════════════════════════════════════════════════════════════╗
║  ✓ SITUATION IMPROVING                                     ║
║  Customer responding well to empathy                       ║
╠════════════════════════════════════════════════════════════╣
║  NEXT STEPS:                                               ║
║  1. Check refund status in system                          ║
║  2. If not processed, escalate to finance team             ║
║  3. Offer goodwill gesture (10% discount on next order)    ║
╚════════════════════════════════════════════════════════════╝
```

## Acceptance Criteria

- [ ] Real-time analysis of customer-agent conversation
- [ ] Provides contextual suggestions to agent
- [ ] Surfaces relevant knowledge base articles
- [ ] Alerts on escalation triggers
- [ ] Supports audio (whisper) and visual dashboard modes
- [ ] Suggests response improvements
- [ ] Tracks agent performance metrics
- [ ] Latency < 1 second for suggestions
- [ ] Customer cannot hear coaching

## Dependencies

- STT for both customer and agent audio streams
- Sentiment Analysis Processor
- Intent Classification Service
- Knowledge Base integration
- WebSocket for real-time dashboard
- TTS for whisper mode (optional)

## Notes

- Start with visual dashboard mode (easier to implement)
- Audio whisper mode requires careful audio routing
- Consider privacy implications (agent monitoring)
- Balance helpfulness vs. intrusiveness
- Could be used for quality assurance and training
- Requires opt-in from agents (privacy/legal considerations)
