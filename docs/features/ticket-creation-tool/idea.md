---
id: ticket-creation-tool
name: Support Ticket Creation Tool
type: Feature
priority: P2
effort: Small
impact: Medium
created: 2026-02-02
---

# Support Ticket Creation Tool

## Problem Statement

When the AI agent cannot resolve an issue or when a customer needs follow-up, there's no systematic way to create a support ticket. Issues discussed on the call can be lost without proper documentation and tracking.

## Proposed Solution

Create an automated ticket creation tool that generates support tickets from conversation context, categorizes them appropriately, and links them to customer records.

### Supported Ticketing Systems

1. **Zendesk** - Popular support platform
2. **Salesforce Service Cloud** - Enterprise CRM with service module
3. **Freshdesk** - Modern support platform
4. **Jira Service Management** - IT service management
5. **Custom API** - Generic connector

### Tools to Implement

1. **`create_support_ticket`** - Auto-generate ticket from conversation
2. **`categorize_issue`** - Classify and route to correct team
3. **`add_ticket_note`** - Add updates to existing tickets
4. **`escalate_ticket`** - Raise priority or change assignment

### Technical Design

```python
# app/tools/builtin/ticket_tools.py

from app.tools import ToolDefinition, ToolParameter, ToolCategory, success_result, error_result
from app.services.ticket_service import TicketServiceFactory

class TicketCreationTool:
    """Automated support ticket creation and management."""
    
    def __init__(self):
        self.ticket_service = TicketServiceFactory.get_ticket_service()
    
    async def create_support_ticket_executor(self, arguments: dict, context: ToolContext) -> ToolResult:
        """Create a support ticket from conversation."""
        customer_id = context.get_customer_id()
        
        # Auto-generate ticket details from conversation
        issue_summary = await self._generate_issue_summary(context)
        category = await self._categorize_issue(context)
        priority = self._determine_priority(context)
        
        try:
            ticket = await self.ticket_service.create_ticket(
                customer_id=customer_id,
                subject=issue_summary["subject"],
                description=issue_summary["description"],
                category=category,
                priority=priority,
                source="voice_ai",
                conversation_transcript=context.get_transcript(),
                metadata={
                    "session_id": context.session_id,
                    "ai_handled": True,
                    "resolution_attempted": True,
                    "customer_sentiment": context.get_sentiment(),
                }
            )
            
            return success_result({
                "ticket_created": True,
                "ticket_id": ticket["id"],
                "ticket_number": ticket["ticket_number"],
                "subject": ticket["subject"],
                "priority": ticket["priority"],
                "estimated_response": ticket.get("sla_response_time"),
            })
        except Exception as e:
            return error_result(f"Failed to create ticket: {str(e)}")
    
    async def _generate_issue_summary(self, context: ToolContext) -> dict:
        """Generate ticket subject and description from conversation."""
        # Use LLM to summarize the issue
        transcript = context.get_transcript()
        
        summary_prompt = f"""
        Based on this customer conversation, generate:
        1. A concise subject line (max 10 words)
        2. A detailed description of the issue
        
        Conversation:
        {transcript}
        
        Format as JSON:
        {{
            "subject": "...",
            "description": "..."
        }}
        """
        
        # Call LLM for summarization
        summary = await self.llm_service.generate(summary_prompt)
        return json.loads(summary)
    
    def _determine_priority(self, context: ToolContext) -> str:
        """Determine ticket priority based on context."""
        # High priority triggers
        if context.get_sentiment().get("frustration_score", 0) > 0.7:
            return "high"
        
        if context.get_auth_level().value == "high":
            # Premium customers get higher priority
            return "high"
        
        if any(keyword in context.get_transcript().lower() 
               for keyword in ["urgent", "emergency", "critical", "outage"]):
            return "high"
        
        # Check repeat contact
        if context.get_customer_context().call_history.total_calls_30d > 2:
            return "medium"
        
        return "low"

# Tool Definition
create_support_ticket_tool = ToolDefinition(
    name="create_support_ticket",
    description="Create a support ticket from the current conversation",
    category=ToolCategory.SUPPORT,
    parameters=[
        ToolParameter(
            name="priority",
            type="string",
            description="Ticket priority: 'low', 'medium', 'high', 'urgent' (auto-detected if not specified)",
            required=False,
        ),
        ToolParameter(
            name="category",
            type="string",
            description="Issue category (auto-detected if not specified)",
            required=False,
        ),
    ],
    executor=TicketCreationTool().create_support_ticket_executor,
    timeout_seconds=5.0,
)
```

### Auto-Categorization

```python
# Ticket categories for routing
TICKET_CATEGORIES = {
    "billing": ["charge", "invoice", "payment", "refund", "billing"],
    "technical": ["error", "bug", "not working", "broken", "technical"],
    "account": ["login", "password", "account access", "profile"],
    "shipping": ["delivery", "shipping", "tracking", "package"],
    "product": ["defective", "warranty", "return", "exchange"],
    "general": [],  # Default
}

async def categorize_issue(self, context: ToolContext) -> str:
    """Categorize issue based on conversation content."""
    transcript = context.get_transcript().lower()
    
    for category, keywords in TICKET_CATEGORIES.items():
        if any(keyword in transcript for keyword in keywords):
            return category
    
    return "general"
```

### Conversation Flow Example

```
Caller: "I've called three times about this billing issue and it's still not fixed!"

Agent: "I apologize for the frustration. Let me create a support ticket to ensure 
        this gets proper attention and escalation. I'll include all the details 
        from our conversation so you won't have to repeat yourself."

[Tool Call: create_support_ticket()]

Agent: "I've created ticket #SUP-2026-4567 for your billing issue. This has been 
        marked as high priority due to the repeat contacts. A billing specialist 
        will review this within 4 hours and contact you directly. Your ticket 
        number is SUP-2026-4567. Is there anything else I can help with today?"
```

## Acceptance Criteria

- [ ] Auto-generates ticket subject and description from conversation
- [ ] Categorizes tickets automatically based on conversation content
- [ ] Determines priority based on sentiment and context
- [ ] Links ticket to customer record in CRM
- [ ] Includes conversation transcript in ticket
- [ ] Integrates with at least 2 ticketing systems
- [ ] Provides ticket number and estimated response time
- [ ] Can add notes to existing tickets

## Dependencies

- CRM Integration Tool (to link tickets to customers)
- LLM service (for summarization)
- Sentiment analysis (for priority determination)

## Notes

- Auto-categorization improves routing accuracy
- Include AI confidence score in ticket metadata
- Flag tickets that may need immediate human attention
- Support ticket templates for common issues
