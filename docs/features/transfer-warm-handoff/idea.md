---
id: transfer-warm-handoff
name: Transfer Warm Handoff
type: Feature
priority: P2
effort: Large
impact: High
created: 2026-02-10
---

# Transfer Warm Handoff

## Problem Statement

Cold transfers (SIP REFER) disconnect the AI abruptly. Customers are left in silence or hearing ring tones during the transfer process. There's no opportunity for the AI to introduce the customer to the human agent or provide a smooth handoff experience.

## Proposed Solution

Implement warm handoff where the AI stays in the call, introduces the customer to the human agent, and then gracefully exits:

1. AI invites human agent to join the Daily room (3-way conference)
2. AI provides spoken summary to the agent: "Hi Sarah, I have John on the line with a billing dispute..."
3. AI informs customer: "John, I'm connecting you with Sarah from billing who can help with your refund..."
4. AI drops from the call once agent confirms they're ready

## Benefits
- Smoother customer experience (no silence/ringing)
- AI can provide verbal context to agent
- Customer knows who they're being transferred to
- Agent has immediate context without checking screen pop

## Affected Areas
- Transfer tool
- Daily transport integration
- Pipeline flow control
- Conference/participant management

## Dependencies
- Basic transfer functionality
- Transfer context packaging (for verbal summary)
- Daily API support for adding participants

## Notes
- More complex than cold transfer - requires managing 3-way call
- Daily stays in call path longer (higher cost)
- Best for high-value or complex transfers
- Could be selectable per-transfer based on priority/context
