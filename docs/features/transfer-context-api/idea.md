---
id: transfer-context-api
name: Transfer Context API
type: Feature
priority: P2
effort: Medium
impact: Medium
created: 2026-02-10
---

# Transfer Context API

## Problem Statement

When calls are transferred to human agents, the receiving system needs a way to retrieve the full conversation context. SIP headers have limited size (~1KB), so we need an API for agents to fetch complete context packages.

## Proposed Solution

Create a REST API endpoint for retrieving transfer context:

**API Endpoint:**
```
GET /api/v1/transfers/{session_id}/context
```

**Response:**
```json
{
  "session_id": "...",
  "customer": {
    "id": "...",
    "name": "...",
    "phone": "...",
    "account_type": "..."
  },
  "conversation": {
    "duration_seconds": 480,
    "turn_count": 12,
    "transcript": "...",
    "intent": "billing_dispute"
  },
  "analysis": {
    "sentiment": {...},
    "issue_summary": "...",
    "suggested_resolution": "..."
  },
  "transfer": {
    "reason": "...",
    "priority": "high",
    "timestamp": "..."
  }
}
```

**Features:**
- Authentication/authorization for agent access
- Context available for 24 hours post-transfer
- Rate limiting to prevent abuse
- CORS support for agent desktop applications

## Affected Areas
- New API endpoint
- Context storage (DynamoDB)
- Authentication/authorization
- API documentation

## Dependencies
- Transfer context packaging feature
- Storage solution for context data
- API Gateway or similar for endpoint exposure

## Notes
- Context should be immutable after transfer
- Consider encryption at rest for sensitive data
- Support webhook notifications when context is accessed
- Could include screen pop URL in SIP headers pointing to this API
