---
name: CRM Capability Agent
type: feature
priority: P1
effort: medium
impact: high
status: shipped
created: 2026-02-19
shipped: 2026-02-20
related-to: dynamic-capability-registry
depends-on: dynamic-capability-registry
---

# CRM Capability Agent

## Problem Statement

The CRM tools (customer lookup, case management, identity verification) are currently embedded inside the voice agent process across three files: `customer_lookup_tool.py`, `case_management_tool.py`, and `verification_tool.py`. All five tools share a dependency on `SimpleCRMService`, which makes HTTP calls to an external CRM API. This means:

- The CRM API dependency (`CRM_API_URL`) is baked into the voice agent's environment and startup.
- Adding CRM tools or modifying verification flows requires redeploying the entire voice agent.
- The CRM service client shares the voice agent's process and error domain -- a CRM API outage could affect tool execution timing for all tools, not just CRM.
- CRM authentication and verification logic (which may evolve frequently as security requirements change) is coupled to the voice pipeline release cycle.
- Another team (e.g., a CRM or security team) cannot own or iterate on these tools independently.

## Vision

Extract all five CRM-related tools into a single **Strands A2A capability agent** deployed as its own ECS Fargate service. The CRM agent owns the `SimpleCRMService` client, all customer and case operations, and the verification flows. The voice agent discovers it via CloudMap and routes tool calls over A2A.

This also opens the door for the CRM agent to internally chain to an Auth Agent via A2A for more sophisticated verification workflows (multi-factor, step-up auth) without the voice agent needing to know about those implementation details.

## Scope

### Tools to Extract

| Current File | Tool Name | Category | Parameters |
|---|---|---|---|
| `customer_lookup_tool.py` | `lookup_customer` | `CUSTOMER_SERVICE` | `phone` (string, required) |
| `case_management_tool.py` | `create_support_case` | `CUSTOMER_SERVICE` | `customer_id`, `subject`, `description` (required); `category`, `priority` (optional) |
| `case_management_tool.py` | `add_case_note` | `CUSTOMER_SERVICE` | `case_id`, `content` (required) |
| `verification_tool.py` | `verify_account_number` | `AUTHENTICATION` | `customer_id`, `last4` (required) |
| `verification_tool.py` | `verify_recent_transaction` | `AUTHENTICATION` | `customer_id`, `date`, `amount`, `merchant` (required) |

### Service Dependencies to Port

- **`SimpleCRMService`** (`app/services/crm_service.py`) -- HTTP client for the CRM API
- **Configuration:** `CRM_API_URL` environment variable

### What Stays in the Voice Agent

- The `FunctionCallFillerProcessor` -- covers latency during A2A calls
- The Pipecat tool handler registration -- handled by the A2A tool adapter
- No CRM-specific system prompt fragments (model-driven tool use from `@tool` docstrings)

## Technical Approach

### CRM Agent Implementation

```python
from strands import Agent, tool
from strands.models import BedrockModel
from strands.multiagent.a2a import A2AServer

# Port SimpleCRMService or use it as a dependency
from crm_client import CRMClient

crm = CRMClient(base_url=os.environ["CRM_API_URL"])

@tool
def lookup_customer(phone: str) -> dict:
    """Search for a customer by their phone number and retrieve their profile
    information. Use this tool when you need to identify a customer, verify
    their account, or check their open cases. Returns the customer's name,
    account type, and any open support cases. Always use this tool at the
    start of a call to identify the caller.

    Args:
        phone: The customer's phone number (e.g., '555-0100').
    """
    # Port from customer_lookup_tool.py

@tool
def create_support_case(customer_id: str, subject: str, description: str,
                        category: str = "general", priority: str = "medium") -> dict:
    """Create a new support case for a customer. Use this tool when a customer
    has a new issue that needs to be tracked, such as a billing dispute,
    technical problem, or account question. The case will be assigned a unique
    ticket number for future reference.

    Args:
        customer_id: The customer's unique ID (from lookup_customer result).
        subject: Brief summary of the issue.
        description: Detailed description of the issue and what the customer needs.
        category: Category: billing, technical, account, order, or general.
        priority: Priority: low, medium, high, or urgent.
    """
    # Port from case_management_tool.py

@tool
def add_case_note(case_id: str, content: str) -> dict:
    """Add a note to an existing support case. Use this to document important
    information during a call, such as troubleshooting steps taken, customer
    requests, or resolution details.

    Args:
        case_id: The case ID (e.g., 'TICKET-2026-00001').
        content: The note content to add to the case.
    """
    # Port from case_management_tool.py

@tool
def verify_account_number(customer_id: str, last4: str) -> dict:
    """Verify customer identity using the last 4 digits of their account number.
    Use this for Knowledge-Based Authentication (KBA) before discussing sensitive
    account information. Ask the customer: 'For security purposes, please provide
    the last 4 digits of your account number.'

    Args:
        customer_id: The customer's unique ID (from lookup_customer result).
        last4: The last 4 digits of the customer's account number.
    """
    # Port from verification_tool.py

@tool
def verify_recent_transaction(customer_id: str, date: str, amount: float,
                              merchant: str) -> dict:
    """Verify customer identity using details of their most recent transaction.
    Use this as an alternative verification method if account number verification
    fails. Ask the customer: 'For security, please tell me the date, amount, and
    merchant of your most recent transaction.'

    Args:
        customer_id: The customer's unique ID (from lookup_customer result).
        date: Transaction date in YYYY-MM-DD format.
        amount: Transaction amount in dollars (e.g., 89.99).
        merchant: Merchant or business name.
    """
    # Port from verification_tool.py

agent = Agent(
    name="CRM Agent",
    description="Customer relationship management: lookup customers, manage support cases, and verify identity",
    model=BedrockModel(model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    tools=[lookup_customer, create_support_case, add_case_note,
           verify_account_number, verify_recent_transaction],
)

a2a_server = A2AServer(agent=agent, host="0.0.0.0", port=8080)
a2a_server.serve()
```

### Infrastructure

- **CDK stack:** `infrastructure/src/stacks/crm-agent-stack.ts` using `CapabilityAgentConstruct`
- **CloudMap:** Auto-registers in `voice-agent-capabilities` namespace
- **IAM:** Minimal -- only needs network access to CRM API (no Bedrock KB permissions)
- **Environment:** `CRM_API_URL` from SSM
- **Resources:** 256 CPU, 512 MB -- CRM calls are HTTP I/O-bound
- **Network:** Security group allowing outbound to CRM API endpoint

### Future: Auth Agent Chaining

The CRM agent could internally chain to a dedicated Auth Agent for advanced verification:
```
Voice Agent LLM → verify_account_number → CRM Agent → Auth Agent (via A2A)
```
This is transparent to the voice agent -- it just sees the verification result. The CRM agent handles the orchestration internally.

## Affected Areas

- New: `backend/agents/crm-agent/main.py`
- New: `backend/agents/crm-agent/crm_client.py` (ported from `app/services/crm_service.py`)
- New: `backend/agents/crm-agent/Dockerfile`
- New: `backend/agents/crm-agent/requirements.txt`
- New: `infrastructure/src/stacks/crm-agent-stack.ts`
- Modified: `pipeline_ecs.py` -- remove CRM tool registration from `_register_tools()` when registry enabled

## Validation Criteria

- [ ] CRM agent deploys independently and registers in CloudMap
- [ ] Agent Card auto-generated with all 5 skills
- [ ] Voice agent discovers CRM agent via AgentRegistry polling
- [ ] All 5 CRM tools work via A2A: lookup, create case, add note, verify account, verify transaction
- [ ] CRM API errors are handled gracefully and returned as tool error results
- [ ] Latency overhead <50ms vs. local tool execution (within VPC)
- [ ] CRM agent can be redeployed independently without voice agent restart
- [ ] Verification tools correctly report success/failure states

## Dependencies

- `dynamic-capability-registry` -- Must be implemented first (AgentRegistry, A2A tool adapter, CloudMap namespace)
- `simple-crm-system` (shipped) -- Existing CRM service code to port
- `strands-agents[a2a]>=1.15.0`
- External CRM API (existing, already provisioned)
