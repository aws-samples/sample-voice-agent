---
id: payment-processing-tool
name: Payment Processing Tool
type: Feature
priority: P2
effort: Large
impact: High
created: 2026-02-02
---

# Payment Processing Tool

## Problem Statement

Customers need to make payments, check balances, or process refunds, but handling payment data requires strict PCI-DSS compliance. The current system has no secure payment processing capability.

## Proposed Solution

Create a PCI-compliant payment processing tool that securely collects payment information and processes transactions without exposing sensitive data to logs or recordings.

### Payment Operations

1. **Process Payment** - Charge a credit card or bank account
2. **Check Balance** - View account balance (after authentication)
3. **Process Refund** - Issue refund to original payment method
4. **View Transaction History** - List recent payments/charges
5. **Setup Recurring Payment** - Schedule automatic payments

### PCI-DSS Compliance Strategy

```
┌─────────────────────────────────────────────────────────────┐
│              PCI-DSS Compliant Payment Flow                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. PAUSE RECORDING                                          │
│     ┌─────────────┐                                          │
│     │   Daily     │ ──► Pause call recording                 │
│     │  Transport  │     (DTMF/sensitive data incoming)       │
│     └─────────────┘                                          │
│                                                              │
│  2. SECURE DATA COLLECTION                                   │
│     ┌─────────────┐                                          │
│     │    DTMF     │ ◄── Customer enters card number          │
│     │  Collection │     via touch tones (not voice)          │
│     └──────┬──────┘                                          │
│            │                                                 │
│     ┌──────▼──────┐                                          │
│     │  Tokenization│ ──► Send to payment processor            │
│     │   Service   │     (Stripe, Square, etc.)               │
│     │             │     Receive token (not card data)        │
│     └─────────────┘                                          │
│                                                              │
│  3. RESUME RECORDING                                         │
│     ┌─────────────┐                                          │
│     │   Daily     │ ──► Resume call recording                │
│     │  Transport  │                                          │
│     └─────────────┘                                          │
│                                                              │
│  4. PROCESS TRANSACTION                                      │
│     ┌─────────────┐                                          │
│     │   Payment   │ ──► Use token to process payment         │
│     │   Processor │     (never store raw card data)          │
│     └─────────────┘                                          │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Technical Design

```python
# app/tools/builtin/payment_tools.py

from app.tools import ToolDefinition, ToolParameter, ToolCategory, success_result, error_result
from app.services.payment_service import PaymentService

class PaymentProcessingTool:
    """PCI-compliant payment processing."""
    
    def __init__(self):
        self.payment_service = PaymentService()
    
    async def check_balance_executor(self, arguments: dict, context: ToolContext) -> ToolResult:
        """Check account balance (requires high auth level)."""
        # Verify authentication level
        if not context.is_authenticated(level="high"):
            return error_result(
                "High authentication required to view balance. "
                "Please verify additional information."
            )
        
        customer_id = context.get_customer_id()
        
        try:
            balance = await self.payment_service.get_balance(customer_id)
            return success_result({
                "balance": balance["amount"],
                "currency": balance["currency"],
                "due_date": balance.get("due_date"),
            })
        except Exception as e:
            return error_result(f"Failed to retrieve balance: {str(e)}")
    
    async def process_payment_executor(self, arguments: dict, context: ToolContext) -> ToolResult:
        """Process payment (card data collected via DTMF)."""
        if not context.is_authenticated(level="high"):
            return error_result("High authentication required for payments")
        
        amount = arguments.get("amount")
        payment_token = arguments.get("payment_token")  # Token from DTMF collection
        
        try:
            result = await self.payment_service.process_payment(
                customer_id=context.get_customer_id(),
                amount=amount,
                payment_token=payment_token,
            )
            return success_result({
                "success": True,
                "transaction_id": result["transaction_id"],
                "amount": result["amount"],
                "status": result["status"],
                "confirmation_code": result["confirmation_code"],
            })
        except Exception as e:
            return error_result(f"Payment failed: {str(e)}")

# DTMF Collection Helper
async def collect_payment_info_dtmf(transport, session_id: str) -> dict:
    """
    Securely collect payment info via DTMF tones.
    
    This is PCI-compliant because:
    - Recording is paused during collection
    - DTMF tones are not logged
    - Only tokenized data is returned
    """
    # Pause recording
    await transport.pause_recording(session_id)
    
    try:
        # Collect card number (16 digits)
        card_number = await transport.collect_dtmf(
            session_id=session_id,
            expected_length=16,
            prompt="Please enter your 16-digit card number",
        )
        
        # Collect expiration date (4 digits: MMYY)
        expiry = await transport.collect_dtmf(
            session_id=session_id,
            expected_length=4,
            prompt="Enter expiration date as month and year, like 0 5 2 7 for May 2027",
        )
        
        # Collect CVV (3-4 digits)
        cvv = await transport.collect_dtmf(
            session_id=session_id,
            expected_length=3,
            max_length=4,
            prompt="Enter the 3-digit security code on the back of your card",
        )
        
        # Tokenize via payment processor
        token = await tokenize_card_data(card_number, expiry, cvv)
        
        return {"payment_token": token}
        
    finally:
        # Always resume recording
        await transport.resume_recording(session_id)

# Tool Definitions
check_balance_tool = ToolDefinition(
    name="check_balance",
    description="Check customer's account balance (requires authentication)",
    category=ToolCategory.PAYMENT,
    parameters=[],
    executor=PaymentProcessingTool().check_balance_executor,
    timeout_seconds=3.0,
)

process_payment_tool = ToolDefinition(
    name="process_payment",
    description="Process a payment using tokenized card data",
    category=ToolCategory.PAYMENT,
    parameters=[
        ToolParameter(
            name="amount",
            type="number",
            description="Payment amount",
            required=True,
        ),
        ToolParameter(
            name="payment_token",
            type="string",
            description="Tokenized payment method (from DTMF collection)",
            required=True,
        ),
    ],
    executor=PaymentProcessingTool().process_payment_executor,
    timeout_seconds=10.0,
)
```

### Supported Payment Processors

1. **Stripe** - Developer-friendly, excellent APIs
2. **Square** - Good for small business integration
3. **PayPal/Braintree** - Wide consumer adoption
4. **Adyen** - Enterprise-grade, global coverage

### Conversation Flow Example

```
Caller: "I'd like to pay my bill"

Agent: "I can help you with that. First, I need to authenticate your account 
        for security. Could you provide the last 4 digits of your account number?"

[Authentication flow...]

Agent: "Thank you. Your current balance is $127.50, due on February 15th. 
        Would you like to pay the full amount?"

Caller: "Yes"

Agent: "For security, I'll need to collect your payment information. Please 
        use your phone's keypad to enter the information. I'll pause recording 
        during this process."

[Recording paused]

Agent: "Please enter your 16-digit card number using your keypad..."

[DTMF collection: 4-5-5-6-...]

Agent: "Enter expiration date as month and year..."

[DTMF collection: 0-5-2-7]

Agent: "Enter the 3-digit security code..."

[DTMF collection: 1-2-3]

[Recording resumed]

[Tool Call: process_payment(amount=127.50, payment_token="tok_visa_xxx")]

Agent: "Perfect! Your payment of $127.50 has been processed successfully. 
        Your confirmation number is PAY-2026-789456. You'll receive an email 
        receipt shortly. Your account balance is now $0.00. Is there anything 
        else I can help you with?"
```

## Acceptance Criteria

- [ ] PCI-DSS compliant payment collection (no card data in logs/recordings)
- [ ] DTMF-based card entry (not voice)
- [ ] Can check account balance
- [ ] Can process payments
- [ ] Can process refunds
- [ ] Can view transaction history
- [ ] Integrates with at least 2 payment processors
- [ ] Recording automatically pauses during payment collection
- [ ] Sends confirmation receipts (email/SMS)
- [ ] Handles payment failures gracefully

## Dependencies

- Authentication Tool (high level required)
- CRM Integration (to link payments to accounts)
- Payment processor account (Stripe, Square, etc.)
- DTMF support in Daily transport
- Recording pause/resume capability

## Notes

- Never log raw card numbers, CVV, or expiration dates
- Use tokenization for all payment methods
- Implement retry logic for failed payments
- Support multiple payment methods (card, bank account)
- Consider implementing 3D Secure for added protection
- Regular PCI compliance audits required
