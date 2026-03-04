---
id: transfer-smart-routing
name: Transfer Smart Routing
type: Feature
priority: P2
effort: Large
impact: Medium
created: 2026-02-10
---

# Transfer Smart Routing

## Problem Statement

All transfers currently go to a single destination. There's no intelligence in routing customers to the optimal queue or agent based on their needs, resulting in longer wait times and multiple transfers.

## Proposed Solution

Implement intelligent routing that selects the best destination based on:

- **Intent classification** - Route billing issues to billing, technical to tech support
- **Agent skills matching** - Match customer needs to agent expertise
- **Queue depth/wait times** - Avoid overloaded queues when possible
- **Customer priority** - VIP customers to priority queues
- **Sentiment analysis** - Frustrated customers to experienced agents
- **Time of day** - Route to appropriate regional teams

## Routing Logic Example
```
if intent == "billing_dispute" and sentiment == "frustrated":
    route_to = "billing_priority_queue"
elif intent == "technical_support" and account_type == "enterprise":
    route_to = "enterprise_tech_queue"
else:
    route_to = "general_queue"
```

## Affected Areas
- Transfer tool
- Intent classification service (new dependency)
- Queue metrics integration
- Routing configuration

## Dependencies
- Intent classification service
- CCaaS queue metrics API access
- Transfer context packaging (for routing decisions)

## Notes
- Requires integration with CCaaS (Genesys, Amazon Connect, etc.)
- Queue metrics need to be real-time or near real-time
- Fallback routing essential for when APIs fail
- Could use overflow queues when primary is busy
