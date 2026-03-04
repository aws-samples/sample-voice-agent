---
id: authentication-tool
name: Customer Authentication Tool
type: Feature
priority: P2
effort: Medium
impact: High
status: backlog
created: 2026-02-02
notes: Phase 1 KBA (verify_account_number, verify_recent_transaction) shipped as part of CRM Capability Agent. Remaining scope is Phases 2-3 (PIN/DTMF, MFA).
---

# Customer Authentication Tool

## Problem Statement

Before accessing sensitive customer data or performing account actions, the voice agent must verify the caller's identity. Current implementation has no authentication mechanism, creating security and compliance risks.

Authentication methods needed:
- Knowledge-based (account numbers, recent transactions, personal info)
- PIN/password verification
- Multi-factor authentication (SMS, email)

## Proposed Solution

Create a flexible authentication framework that supports multiple verification methods with configurable security levels.

### Authentication Methods

#### Phase 1: Knowledge-Based Authentication (KBA)

Verify identity using information the customer knows:

```python
AUTH_LEVELS = {
    "low": {
        "methods": ["account_last4"],
        "description": "Basic identification",
    },
    "medium": {
        "methods": ["account_last4", "recent_transaction"],
        "description": "Standard verification",
    },
    "high": {
        "methods": ["account_last4", "recent_transaction", "personal_info"],
        "description": "Sensitive operations",
    },
}
```

#### Phase 2: PIN/Password

Support PIN entry via DTMF tones or voice:

```python
async def collect_pin_dtmf(self, session_id: str) -> str:
    """Collect PIN via touch-tone input."""
    await self.daily_client.enable_dtmf_collection(session_id)
    pin = await self.daily_client.wait_for_dtmf(
        session_id=session_id,
        expected_digits=4,
        timeout_seconds=30,
    )
    return pin
```

#### Phase 3: Multi-Factor Authentication (MFA)

Send verification codes via SMS or email:

```python
async def send_mfa_code(self, customer_id: str, method: str) -> bool:
    """Send MFA code via SMS or email."""
    code = generate_secure_code(length=6)
    await self.auth_store.store_verification_code(
        customer_id=customer_id,
        code=code,
        ttl_seconds=300,
    )
    # Send via SNS (SMS) or SES (email)
```

### Tools to Implement

1. **`authenticate_customer`** - Main authentication orchestrator
2. **`verify_kba_answer`** - Check knowledge-based answers
3. **`verify_pin`** - Validate PIN entry
4. **`send_mfa_code`** - Send MFA verification code
5. **`verify_mfa_code`** - Validate MFA code
6. **`check_auth_status`** - Verify current authentication level

### Security Considerations

1. **Failed Attempt Limits**: Lock out after 3 failed attempts
2. **Session Timeout**: Re-authenticate after 10 minutes of inactivity
3. **Audit Logging**: Log all authentication attempts
4. **PCI Compliance**: Pause recording during PIN entry
5. **Encryption**: All PII encrypted at rest and in transit

## Acceptance Criteria

- [ ] Supports knowledge-based authentication (account numbers, recent transactions)
- [ ] Supports PIN verification via DTMF
- [ ] Supports SMS/email MFA
- [ ] Configurable authentication levels (low/medium/high)
- [ ] Failed attempt tracking and lockout
- [ ] Session timeout and re-authentication
- [ ] Audit logging of all auth events
- [ ] Graceful escalation on auth failure

## Dependencies

- CRM Integration Tool (for retrieving KBA data)
- DynamoDB for auth state storage
- SMS/Email service (SNS, SES)
- DTMF support in Daily transport
