# Call Scenarios

Three representative test call scenarios for validating the multi-agent Flows system. Each scenario exercises different specialist agents, transition patterns, and edge cases.

> **Prerequisites:** All three capability agents (KB, CRM, Appointment) deployed, data seeded, and Flows mode enabled. See [Deployment Guide](../../infrastructure/DEPLOYMENT.md#deploy-capability-agents-a2a).

## Scenario 1: Sarah's Printer Problem

**Tests:** KB troubleshooting, dependency gating redirect, CRM customer lookup, Appointment scheduling, 3+ transitions.

**Duration:** ~4 minutes

### Call Script

| Turn | Caller Says | Expected Agent | Expected Behavior |
|------|-------------|---------------|-------------------|
| 1 | *(wait for greeting)* | Orchestrator | Greets caller, asks how it can help |
| 2 | "Hi, my printer keeps jamming and I can't fix it." | Orchestrator | Identifies tech support intent, transfers to KB specialist |
| 3 | *(wait for specialist)* | KB Specialist | Introduces itself, calls `search_knowledge_base` for printer jam troubleshooting |
| 4 | "I already tried all of that. I think I need someone to come fix it." | KB Specialist | Recognizes need for on-site repair, initiates transfer to Appointment |
| 5 | *(wait for redirect)* | CRM Specialist | **Dependency gating**: KB tried to transfer to Appointment, but `customer_id` not satisfied. Redirected to CRM. CRM asks for identifying info. |
| 6 | "My phone number is 555-0101." | CRM Specialist | Calls `lookup_customer`, finds Sarah Johnson (cust-002). Calls `create_support_case` for the printer issue. Transfers to Appointment. |
| 7 | *(wait for specialist)* | Appointment Specialist | `customer_id` now satisfied. Asks about scheduling preferences. |
| 8 | "Tomorrow morning would work, for an on-site repair." | Appointment Specialist | Calls `check_availability` then `book_appointment` for Sarah. Confirms details. |
| 9 | "That's perfect, thank you!" | Appointment Specialist | Wraps up, transfers back to orchestrator or hangs up. |

### What to Verify

- [ ] Orchestrator correctly identifies tech support intent (not billing or scheduling)
- [ ] KB specialist searches knowledge base and provides troubleshooting steps
- [ ] Transfer from KB to Appointment is **redirected** to CRM (dependency gating)
- [ ] CRM successfully looks up customer by phone number
- [ ] CRM creates a support case
- [ ] Transfer from CRM to Appointment succeeds (customer_id now satisfied)
- [ ] Appointment checks availability and books the visit
- [ ] No audible gap or silence during transitions
- [ ] Total transitions: 3-4 (orchestrator -> KB -> CRM -> appointment, optionally -> orchestrator)

### CloudWatch Verification

```
# Check transition count for the session
fields @timestamp, from_node, to_node, reason, transition_count
| filter event = "agent_transition"
| sort @timestamp asc
| limit 20
```

---

## Scenario 2: Billing Inquiry with Account Verification

**Tests:** CRM specialist (5 tools), direct orchestrator-to-CRM routing, no dependency gating involved.

**Duration:** ~2 minutes

### Call Script

| Turn | Caller Says | Expected Agent | Expected Behavior |
|------|-------------|---------------|-------------------|
| 1 | *(wait for greeting)* | Orchestrator | Greets caller |
| 2 | "I need to check on my account and a recent support case." | Orchestrator | Identifies billing/account intent, transfers to CRM specialist |
| 3 | *(wait for specialist)* | CRM Specialist | Introduces itself, asks for identifying information |
| 4 | "My account number is... actually, look me up by phone: 555-0100." | CRM Specialist | Calls `lookup_customer`, finds John Smith (cust-001, premium) |
| 5 | "Can you verify my last transaction?" | CRM Specialist | Calls `verify_recent_transaction` for John Smith |
| 6 | "And can you add a note to my open case that the issue is getting worse?" | CRM Specialist | Calls `add_case_note` to the existing support case |
| 7 | "That's all, thanks." | CRM Specialist | Transfers back to orchestrator |
| 8 | *(wait for orchestrator)* | Orchestrator | Asks "Is there anything else?" |
| 9 | "No, that's it. Goodbye." | Orchestrator | Calls `hangup_call` |

### What to Verify

- [ ] Orchestrator correctly routes to CRM (not KB)
- [ ] CRM uses `lookup_customer` with phone number
- [ ] CRM calls `verify_recent_transaction` successfully
- [ ] CRM calls `add_case_note` to an existing case
- [ ] Return to orchestrator includes continuation context ("Is there anything else?")
- [ ] `hangup_call` works with proper reason parameter
- [ ] Total transitions: 2 (orchestrator -> CRM -> orchestrator)

---

## Scenario 3: Direct Appointment Management

**Tests:** Appointment specialist (multiple tool calls), reschedule flow, cancel flow, dependency gating when no customer_id.

**Duration:** ~3 minutes

### Call Script

| Turn | Caller Says | Expected Agent | Expected Behavior |
|------|-------------|---------------|-------------------|
| 1 | *(wait for greeting)* | Orchestrator | Greets caller |
| 2 | "I need to reschedule my appointment." | Orchestrator | Identifies scheduling intent, transfers to Appointment |
| 3 | *(wait for redirect)* | CRM Specialist | **Dependency gating**: Appointment requires `customer_id`. Redirected to CRM first. |
| 4 | "I'm Michael Chen, phone number 555-0102." | CRM Specialist | Calls `lookup_customer`, finds Michael Chen (cust-003, enterprise). Transfers to Appointment. |
| 5 | *(wait for specialist)* | Appointment Specialist | `customer_id` satisfied. Calls `list_appointments` to show Michael's upcoming appointments. |
| 6 | "I need to move the hardware upgrade to next week." | Appointment Specialist | Calls `reschedule_appointment` with new date/time |
| 7 | "Actually, can you just cancel it entirely?" | Appointment Specialist | Calls `cancel_appointment` |
| 8 | "And book a general consultation instead, for next Friday afternoon." | Appointment Specialist | Calls `check_availability` then `book_appointment` for general consultation |
| 9 | "Great, that's everything." | Appointment Specialist | Wraps up, hangs up or transfers to orchestrator |

### What to Verify

- [ ] Orchestrator identifies scheduling intent even without explicit "book" language
- [ ] Transfer to Appointment is redirected to CRM (dependency gating)
- [ ] CRM lookup succeeds and transfers to Appointment
- [ ] `list_appointments` returns Michael's existing appointments
- [ ] `reschedule_appointment` changes the date/time
- [ ] `cancel_appointment` cancels the rescheduled appointment
- [ ] `check_availability` + `book_appointment` books new consultation
- [ ] Multiple Appointment tools work in sequence within the same node (no re-transfer needed)
- [ ] Total transitions: 2-3 (orchestrator -> CRM -> appointment)

---

## Demo Customer Data

All scenarios use the same seeded customer data. Ensure CRM and Appointment data are seeded before testing.

| Customer | ID | Phone | Account Type |
|----------|----|-------|-------------|
| John Smith | cust-001 | 555-0100 | premium |
| Sarah Johnson | cust-002 | 555-0101 | basic |
| Michael Chen | cust-003 | 555-0102 | enterprise |

### Seed Commands

```bash
# Seed CRM data
CRM_URL=$(aws ssm get-parameter --name "/voice-agent/crm/api-url" --query 'Parameter.Value' --output text)
curl -s -X POST "$CRM_URL/admin/seed" | python3 -m json.tool

# Seed Appointment data
APPT_URL=$(aws ssm get-parameter --name "/voice-agent/appointments/api-url" --query 'Parameter.Value' --output text)
curl -s -X POST "$APPT_URL/admin/seed" | python3 -m json.tool
```

## Related Documentation

- [Multi-Agent Flows Guide](../guides/multi-agent-flows.md) -- Full operator guide
- [Deployment Guide](../../infrastructure/DEPLOYMENT.md) -- Deployment and enablement steps
