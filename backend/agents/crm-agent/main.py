#!/usr/bin/env python3
"""CRM Capability Agent.

A standalone Strands A2A agent that provides customer relationship management
capabilities via the A2A protocol. Deployed as an independent ECS Fargate
service, discovered by the voice agent via CloudMap.

The agent wraps 5 CRM tools behind Strands @tool decorators and exposes them
via A2AServer. The voice agent's LLM sees the tool descriptions (from @tool
docstrings) and invokes them over A2A when appropriate.

Tools provided:
    - lookup_customer: Search customer by phone number
    - create_support_case: Create a new support case
    - add_case_note: Add a note to an existing case
    - verify_account_number: KBA via account number last 4 digits
    - verify_recent_transaction: KBA via recent transaction details

Environment variables:
    CRM_API_URL: Base URL for the CRM REST API (required)
    AWS_REGION: AWS region (default: us-east-1)
    LLM_MODEL_ID: Bedrock model for agent reasoning
        (default: us.anthropic.claude-haiku-4-5-20251001-v1:0)
    PORT: Server port (default: 8000)
    AGENT_NAME: Agent name for logging (default: crm)
"""

import os
import sys
import time

import requests
import structlog
from crm_client import CRMClient, CRMError
from strands import Agent, tool
from strands.models import BedrockModel
from strands.multiagent.a2a import A2AServer

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger(__name__)

# Configuration from environment
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
CRM_API_URL = os.getenv("CRM_API_URL", "")
LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
PORT = int(os.getenv("PORT", "8000"))

# Shared CRM client instance (initialized lazily)
_crm_client = None


def _get_task_private_ip() -> str | None:
    """Get this ECS task's private IPv4 address from the metadata endpoint.

    In ECS Fargate, the metadata endpoint provides task network info.
    We use this so the Agent Card advertises a reachable URL instead of 0.0.0.0.

    Returns:
        Private IP string, or None if not running in ECS.
    """
    metadata_uri = os.getenv("ECS_CONTAINER_METADATA_URI_V4")
    if not metadata_uri:
        return None

    try:
        resp = requests.get(f"{metadata_uri}/task", timeout=2)
        resp.raise_for_status()
        task_meta = resp.json()
        # Containers[0].Networks[0].IPv4Addresses[0]
        containers = task_meta.get("Containers", [])
        for container in containers:
            networks = container.get("Networks", [])
            for network in networks:
                addrs = network.get("IPv4Addresses", [])
                if addrs:
                    return addrs[0]
    except Exception as e:
        logger.warning("task_ip_metadata_failed", error=str(e))

    return None


def _get_crm_client() -> CRMClient:
    """Lazy-initialize the CRM client."""
    global _crm_client
    if _crm_client is None:
        _crm_client = CRMClient(base_url=CRM_API_URL)
    return _crm_client


# =============================================================================
# Tool: lookup_customer
# =============================================================================


@tool
def lookup_customer(phone: str) -> dict:
    """Search for a customer by their phone number and retrieve their profile
    information. Use this tool when you need to identify a customer, verify
    their account, or check their open cases. Returns the customer's name,
    account type, and any open support cases. Always use this tool at the
    start of a call to identify the caller.

    Args:
        phone: The customer's phone number (e.g., '555-0100').

    Returns:
        Dictionary with customer data and open cases, or not-found message.
    """
    if not phone or not phone.strip():
        return {"found": False, "error": "Phone number is required"}

    phone = phone.strip()

    tool_start = time.monotonic()

    try:
        crm = _get_crm_client()

        if not crm.is_configured():
            return {
                "found": False,
                "error": "CRM service is not configured",
            }

        # Search for customer
        search_start = time.monotonic()
        customer = crm.search_customer_by_phone(phone)
        search_ms = (time.monotonic() - search_start) * 1000

        if not customer:
            logger.info(
                "customer_not_found",
                phone=phone,
                search_ms=round(search_ms, 1),
            )
            return {
                "found": False,
                "phone": phone,
                "message": f"No customer found with phone number {phone}",
            }

        # Get open cases
        cases_start = time.monotonic()
        open_cases = crm.get_customer_cases(customer.customer_id, status="open")
        cases_ms = (time.monotonic() - cases_start) * 1000

        total_ms = (time.monotonic() - tool_start) * 1000
        logger.info(
            "customer_lookup_complete",
            phone=phone,
            search_ms=round(search_ms, 1),
            cases_ms=round(cases_ms, 1),
            total_ms=round(total_ms, 1),
        )

        result = {
            "found": True,
            "customer": customer.to_dict(),
            "open_cases": [case.to_dict() for case in open_cases],
            "open_case_count": len(open_cases),
        }

        # Add helpful summary message for the agent
        if open_cases:
            case_summaries = [
                f"{case.case_id}: {case.subject} ({case.priority} priority)"
                for case in open_cases
            ]
            result["message"] = (
                f"Found customer {customer.full_name} ({customer.account_type} account). "
                f"They have {len(open_cases)} open case(s): {'; '.join(case_summaries)}"
            )
        else:
            result["message"] = (
                f"Found customer {customer.full_name} ({customer.account_type} account). "
                f"No open cases."
            )

        return result

    except CRMError as e:
        logger.error("crm_error_lookup_customer", error=e.message)
        return {"found": False, "error": f"CRM error: {e.message}"}
    except Exception as e:
        logger.exception("unexpected_error_lookup_customer")
        return {"found": False, "error": f"Unexpected error: {str(e)}"}


# =============================================================================
# Tool: create_support_case
# =============================================================================


@tool
def create_support_case(
    customer_id: str,
    subject: str,
    description: str,
    category: str = "general",
    priority: str = "medium",
) -> dict:
    """Create a new support case for a customer. Use this tool when a customer
    has a new issue that needs to be tracked, such as a billing dispute,
    technical problem, or account question. The case will be assigned a unique
    ticket number that can be referenced in future conversations.

    Args:
        customer_id: The customer's unique ID (from lookup_customer result).
        subject: Brief summary of the issue (e.g., 'Billing dispute - October charge').
        description: Detailed description of the issue and what the customer needs.
        category: Category of the issue: billing, technical, account, order, or general.
        priority: Priority level: low, medium, high, or urgent (default: medium).

    Returns:
        Dictionary with the created case data and confirmation message.
    """
    # Validate required fields
    if not customer_id or not customer_id.strip():
        return {"created": False, "error": "Customer ID is required"}
    if not subject or not subject.strip():
        return {"created": False, "error": "Case subject is required"}
    if not description or not description.strip():
        return {"created": False, "error": "Case description is required"}

    customer_id = customer_id.strip()
    subject = subject.strip()
    description = description.strip()
    category = (category or "general").strip().lower()
    priority = (priority or "medium").strip().lower()

    # Validate enums
    valid_categories = ["billing", "technical", "account", "order", "general"]
    if category not in valid_categories:
        return {
            "created": False,
            "error": f"Invalid category '{category}'. Must be one of: {', '.join(valid_categories)}",
        }

    valid_priorities = ["low", "medium", "high", "urgent"]
    if priority not in valid_priorities:
        return {
            "created": False,
            "error": f"Invalid priority '{priority}'. Must be one of: {', '.join(valid_priorities)}",
        }

    try:
        crm = _get_crm_client()

        if not crm.is_configured():
            return {"created": False, "error": "CRM service is not configured"}

        create_start = time.monotonic()
        case = crm.create_case(
            customer_id=customer_id,
            subject=subject,
            description=description,
            category=category,
            priority=priority,
        )
        create_ms = (time.monotonic() - create_start) * 1000

        logger.info(
            "case_created",
            case_id=case.case_id,
            create_ms=round(create_ms, 1),
        )

        return {
            "created": True,
            "case": case.to_dict(),
            "message": (
                f"Successfully created case {case.case_id} for customer. "
                f"Subject: {case.subject}. Priority: {case.priority}."
            ),
        }

    except CRMError as e:
        logger.error("crm_error_create_support_case", error=e.message)
        return {"created": False, "error": f"CRM error: {e.message}"}
    except Exception as e:
        logger.exception("unexpected_error_create_support_case")
        return {"created": False, "error": f"Unexpected error: {str(e)}"}


# =============================================================================
# Tool: add_case_note
# =============================================================================


@tool
def add_case_note(case_id: str, content: str) -> dict:
    """Add a note to an existing support case. Use this tool to document
    important information during a call, such as troubleshooting steps taken,
    customer requests, or resolution details. This helps maintain a complete
    history of the case.

    Args:
        case_id: The case ID (e.g., 'TICKET-2026-00001').
        content: The note content to add to the case.

    Returns:
        Dictionary with the updated case data and confirmation message.
    """
    if not case_id or not case_id.strip():
        return {"added": False, "error": "Case ID is required"}
    if not content or not content.strip():
        return {"added": False, "error": "Note content is required"}

    case_id = case_id.strip()
    content = content.strip()

    try:
        crm = _get_crm_client()

        if not crm.is_configured():
            return {"added": False, "error": "CRM service is not configured"}

        case = crm.add_case_note(
            case_id=case_id,
            content=content,
            author="voice-agent",
        )

        return {
            "added": True,
            "case": case.to_dict(),
            "message": f"Successfully added note to case {case_id}. Case now has {len(case.notes)} note(s).",
        }

    except CRMError as e:
        logger.error("crm_error_add_case_note", error=e.message)
        return {"added": False, "error": f"CRM error: {e.message}"}
    except Exception as e:
        logger.exception("unexpected_error_add_case_note")
        return {"added": False, "error": f"Unexpected error: {str(e)}"}


# =============================================================================
# Tool: verify_account_number
# =============================================================================


@tool
def verify_account_number(customer_id: str, last4: str) -> dict:
    """Verify customer identity using the last 4 digits of their account
    number. Use this tool for Knowledge-Based Authentication (KBA) before
    discussing sensitive account information. Ask the customer: 'For security
    purposes, please provide the last 4 digits of your account number.'

    Args:
        customer_id: The customer's unique ID (from lookup_customer result).
        last4: The last 4 digits of the customer's account number.

    Returns:
        Dictionary with verification result (verified: true/false) and message.
    """
    if not customer_id or not customer_id.strip():
        return {"verified": False, "error": "Customer ID is required"}
    if not last4 or not last4.strip():
        return {
            "verified": False,
            "error": "Last 4 digits of account number are required",
        }

    customer_id = customer_id.strip()
    last4 = last4.strip()

    if len(last4) != 4 or not last4.isdigit():
        return {"verified": False, "error": "Please provide exactly 4 digits"}

    try:
        crm = _get_crm_client()

        if not crm.is_configured():
            return {"verified": False, "error": "CRM service is not configured"}

        customer = crm.get_customer(customer_id)

        if not customer:
            return {"verified": False, "error": "Customer not found"}

        if not customer.account_last4:
            return {
                "verified": False,
                "message": "Account verification not available for this customer. No account number on file.",
                "method": "account_number",
            }

        is_verified = crm.verify_account_number(customer, last4)

        if is_verified:
            return {
                "verified": True,
                "message": "Account number verified successfully. Customer identity confirmed.",
                "method": "account_number",
            }
        else:
            return {
                "verified": False,
                "message": "Account number does not match our records. Please try again or use alternative verification.",
                "method": "account_number",
            }

    except CRMError as e:
        logger.error("crm_error_verify_account_number", error=e.message)
        return {"verified": False, "error": f"CRM error: {e.message}"}
    except Exception as e:
        logger.exception("unexpected_error_verify_account_number")
        return {"verified": False, "error": f"Unexpected error: {str(e)}"}


# =============================================================================
# Tool: verify_recent_transaction
# =============================================================================


@tool
def verify_recent_transaction(
    customer_id: str, date: str, amount: float, merchant: str
) -> dict:
    """Verify customer identity using details of their most recent transaction.
    Use this tool as an alternative verification method if account number
    verification fails. Ask the customer: 'For security, please tell me the
    date, amount, and merchant of your most recent transaction.'

    Args:
        customer_id: The customer's unique ID (from lookup_customer result).
        date: Transaction date in YYYY-MM-DD format (e.g., '2026-01-28').
        amount: Transaction amount in dollars (e.g., 89.99).
        merchant: Merchant or business name (e.g., 'TechStore Online').

    Returns:
        Dictionary with verification result (verified: true/false) and message.
    """
    if not customer_id or not customer_id.strip():
        return {"verified": False, "error": "Customer ID is required"}
    if not date or not date.strip():
        return {
            "verified": False,
            "error": "Transaction date is required (YYYY-MM-DD format)",
        }
    if not amount:
        return {"verified": False, "error": "Transaction amount is required"}
    if not merchant or not merchant.strip():
        return {"verified": False, "error": "Merchant name is required"}

    customer_id = customer_id.strip()
    date = date.strip()
    merchant = merchant.strip()

    try:
        crm = _get_crm_client()

        if not crm.is_configured():
            return {"verified": False, "error": "CRM service is not configured"}

        customer = crm.get_customer(customer_id)

        if not customer:
            return {"verified": False, "error": "Customer not found"}

        if not customer.recent_transaction:
            return {
                "verified": False,
                "message": "Transaction verification not available for this customer. No recent transaction on file.",
                "method": "recent_transaction",
            }

        is_verified = crm.verify_recent_transaction(customer, date, amount, merchant)

        if is_verified:
            return {
                "verified": True,
                "message": "Transaction details verified successfully. Customer identity confirmed.",
                "method": "recent_transaction",
            }
        else:
            return {
                "verified": False,
                "message": "Transaction details do not match our records. Please verify the date, amount, and merchant name.",
                "method": "recent_transaction",
            }

    except CRMError as e:
        logger.error("crm_error_verify_recent_transaction", error=e.message)
        return {"verified": False, "error": f"CRM error: {e.message}"}
    except Exception as e:
        logger.exception("unexpected_error_verify_recent_transaction")
        return {"verified": False, "error": f"Unexpected error: {str(e)}"}


# =============================================================================
# Agent setup and server
# =============================================================================


def main():
    """Start the CRM A2A agent server."""
    if not CRM_API_URL:
        logger.warning(
            "crm_api_url_not_set", note="agent will return errors for CRM operations"
        )

    # --- Warm-up: pre-initialize CRM client to reuse TCP connections ---
    warmup_start = time.monotonic()
    try:
        _get_crm_client()
        logger.info(
            "crm_client_warmup_complete",
            elapsed_ms=round((time.monotonic() - warmup_start) * 1000, 1),
        )
    except Exception as e:
        logger.warning("crm_client_warmup_failed", error=str(e))

    model = BedrockModel(
        model_id=LLM_MODEL_ID,
        region_name=AWS_REGION,
    )

    agent = Agent(
        name="CRM Agent",
        description=(
            "Customer relationship management: lookup customers by phone number, "
            "create and manage support cases, add case notes, and verify customer "
            "identity using account numbers or recent transaction details."
        ),
        model=model,
        tools=[
            lookup_customer,
            create_support_case,
            add_case_note,
            verify_account_number,
            verify_recent_transaction,
        ],
        callback_handler=None,
    )

    # --- Warm-up: probe the Strands agent to force BedrockModel initialization ---
    agent_warmup_start = time.monotonic()
    try:
        agent("warmup")
        logger.info(
            "strands_agent_warmup_complete",
            elapsed_ms=round((time.monotonic() - agent_warmup_start) * 1000, 1),
        )
    except Exception as e:
        logger.warning(
            "strands_agent_warmup_failed",
            error=str(e),
            note="will initialize on first real call",
        )

    # Determine the reachable URL for the Agent Card.
    # In ECS Fargate, the server binds to 0.0.0.0 but must advertise the
    # task's private IP so other services can reach it via A2A protocol.
    task_ip = _get_task_private_ip()
    http_url = f"http://{task_ip}:{PORT}/" if task_ip else None

    server = A2AServer(
        agent=agent,
        host="0.0.0.0",
        port=PORT,
        http_url=http_url,
        version="0.1.0",
    )

    logger.info("crm_agent_starting", port=PORT)
    logger.info("crm_config", crm_api_url=CRM_API_URL or "(not configured)")
    logger.info("crm_model", model_id=LLM_MODEL_ID)
    logger.info("agent_card_url", url=http_url or f"http://0.0.0.0:{PORT}/")
    # Disable uvicorn access logs -- CloudMap polls /.well-known/agent-card.json
    # every 30s, producing ~2,880 noise lines/day. Our structlog captures all
    # meaningful request events (tool calls, errors) already.
    server.serve(access_log=False)


if __name__ == "__main__":
    main()
