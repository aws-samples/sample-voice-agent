---
id: crm-integration-tool
name: CRM Integration Tool
type: Feature
priority: P3
effort: Medium
impact: High
status: superseded
created: 2026-02-02
notes: Core CRM capabilities superseded by simple-crm-system (shipped) and crm-capability-agent (shipped). Remaining scope is multi-platform CRM adapters (Salesforce, HubSpot, Zendesk) which are not currently planned.
---

# CRM Integration Tool

## Problem Statement

The voice agent currently operates in isolation without access to customer data. For a production contact center, agents need to:
- Look up customer records by phone number or account ID
- View customer history, preferences, and open cases
- Update customer records during the conversation
- Access contextual information to personalize interactions

Without CRM integration, the agent cannot provide personalized service, leading to poor customer experience and requiring customers to repeat information.

## Proposed Solution

Create a modular CRM integration tool that supports multiple CRM platforms through a unified interface.

### Supported CRM Platforms (Phase 1)

1. **Salesforce** - Industry standard for enterprise
2. **HubSpot** - Popular for mid-market
3. **Zendesk** - Strong in support use cases
4. **Custom API** - Generic REST API connector for bespoke systems

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    CRM Integration Tool                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  Salesforce  │  │   HubSpot    │  │   Zendesk    │       │
│  │   Adapter    │  │   Adapter    │  │   Adapter    │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                  │                  │              │
│         └──────────────────┼──────────────────┘              │
│                            │                                 │
│                   ┌────────▼────────┐                        │
│                   │  Unified CRM    │                        │
│                   │   Interface     │                        │
│                   │  (Tool Schema)  │                        │
│                   └────────┬────────┘                        │
│                            │                                 │
│                   ┌────────▼────────┐                        │
│                   │  Tool Registry  │                        │
│                   │   (Pipecat)     │                        │
│                   └─────────────────┘                        │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Tools to Implement

1. **`search_customer`** - Look up customer by phone, email, or account ID
2. **`get_customer_details`** - Retrieve full customer record
3. **`update_customer_field`** - Update specific fields (notes, preferences, etc.)
4. **`get_customer_cases`** - Retrieve open support tickets/cases
5. **`create_case_note`** - Add notes to existing cases

### Technical Design

```python
# app/tools/builtin/crm_tools.py

from app.tools import ToolDefinition, ToolParameter, ToolCategory, success_result, error_result
from app.services.crm_service import CRMServiceFactory

class CRMIntegrationTool:
    """Unified CRM interface supporting multiple platforms."""
    
    def __init__(self):
        self.crm = CRMServiceFactory.get_crm_service()
    
    async def search_customer_executor(self, arguments: dict, context: ToolContext) -> ToolResult:
        """Search for customer by identifier."""
        identifier = arguments.get("identifier")
        identifier_type = arguments.get("identifier_type", "phone")
        
        try:
            customer = await self.crm.search_customer(identifier, identifier_type)
            if customer:
                context.set_customer_data(customer)
                return success_result({
                    "found": True,
                    "customer_id": customer["id"],
                    "name": customer["name"],
                    "account_status": customer["status"],
                    "summary": customer.get("summary", ""),
                })
            else:
                return success_result({"found": False})
        except Exception as e:
            return error_result(f"CRM lookup failed: {str(e)}")

# Tool Definitions
search_customer_tool = ToolDefinition(
    name="search_customer",
    description="Search for customer record by phone number, email, or account ID",
    category=ToolCategory.CUSTOMER_DATA,
    parameters=[
        ToolParameter(
            name="identifier",
            type="string",
            description="Customer identifier (phone, email, or account ID)",
            required=True,
        ),
        ToolParameter(
            name="identifier_type",
            type="string",
            description="Type of identifier: 'phone', 'email', or 'account_id'",
            required=False,
        ),
    ],
    executor=CRMIntegrationTool().search_customer_executor,
    timeout_seconds=5.0,
)
```

### Configuration

```python
# Environment variables
CRM_PROVIDER=salesforce
CRM_API_KEY_SECRET_ARN=arn:aws:secretsmanager:...
CRM_BASE_URL=https://myinstance.salesforce.com
```

## Acceptance Criteria

- [ ] Can search customers by phone, email, and account ID
- [ ] Retrieves customer profile, status, and summary
- [ ] Can view open cases/tickets
- [ ] Can add notes to cases
- [ ] Supports at least 2 CRM platforms (Salesforce + one other)
- [ ] Response time < 3 seconds for lookups
- [ ] Graceful handling of CRM unavailability
- [ ] Customer data cached in conversation context

## Dependencies

- Tool calling framework (existing)
- AWS Secrets Manager for API credentials
- Session tracking (existing DynamoDB)

## Notes

- Start with Salesforce as primary target (most enterprise demand)
- Use OAuth 2.0 for authentication where possible
- Consider rate limiting and API quotas
- Ensure PII is handled according to compliance requirements
