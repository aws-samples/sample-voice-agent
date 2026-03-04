---
id: appointment-scheduling-tool
name: Appointment Scheduling Tool
type: Feature
priority: P2
effort: Medium
impact: Medium
created: 2026-02-02
---

# Appointment Scheduling Tool

## Problem Statement

Customers often need to schedule appointments (service calls, consultations, deliveries) but the agent cannot access calendar systems to check availability or book time slots. This requires human agent intervention for a routine task.

## Proposed Solution

Create an appointment scheduling tool that integrates with popular calendar systems to check availability, book appointments, and send confirmations.

### Supported Calendar Systems

1. **Google Calendar** - Most common consumer/business choice
2. **Microsoft Outlook/Exchange** - Enterprise standard
3. **Calendly** - Popular scheduling platform
4. **Custom API** - Generic connector for proprietary systems

### Tools to Implement

1. **`check_availability`** - Find available time slots for a date range
2. **`book_appointment`** - Schedule an appointment with customer details
3. **`reschedule_appointment`** - Move existing appointment to new time
4. **`cancel_appointment`** - Cancel scheduled appointment
5. **`get_appointment_details`** - Retrieve existing appointment info

### Technical Design

```python
# app/tools/builtin/scheduling_tools.py

from app.tools import ToolDefinition, ToolParameter, ToolCategory, success_result, error_result
from app.services.calendar_service import CalendarServiceFactory

class AppointmentSchedulingTool:
    """Unified calendar interface for appointment management."""
    
    def __init__(self):
        self.calendar = CalendarServiceFactory.get_calendar_service()
    
    async def check_availability_executor(self, arguments: dict, context: ToolContext) -> ToolResult:
        """Check available time slots."""
        date = arguments.get("date")
        duration_minutes = arguments.get("duration_minutes", 30)
        
        try:
            slots = await self.calendar.get_available_slots(
                date=date,
                duration_minutes=duration_minutes,
            )
            return success_result({
                "date": date,
                "available_slots": slots,
                "slot_count": len(slots),
            })
        except Exception as e:
            return error_result(f"Failed to check availability: {str(e)}")
    
    async def book_appointment_executor(self, arguments: dict, context: ToolContext) -> ToolResult:
        """Book an appointment."""
        customer_id = context.get_customer_id()
        date_time = arguments.get("date_time")
        duration_minutes = arguments.get("duration_minutes", 30)
        purpose = arguments.get("purpose", "")
        
        try:
            appointment = await self.calendar.book_appointment(
                customer_id=customer_id,
                date_time=date_time,
                duration_minutes=duration_minutes,
                purpose=purpose,
            )
            return success_result({
                "booked": True,
                "appointment_id": appointment["id"],
                "date_time": appointment["date_time"],
                "confirmation_code": appointment["confirmation_code"],
            })
        except Exception as e:
            return error_result(f"Failed to book appointment: {str(e)}")

# Tool Definitions
check_availability_tool = ToolDefinition(
    name="check_availability",
    description="Check available appointment slots for a specific date",
    category=ToolCategory.SCHEDULING,
    parameters=[
        ToolParameter(
            name="date",
            type="string",
            description="Date to check (YYYY-MM-DD format)",
            required=True,
        ),
        ToolParameter(
            name="duration_minutes",
            type="integer",
            description="Duration needed in minutes (default: 30)",
            required=False,
        ),
    ],
    executor=AppointmentSchedulingTool().check_availability_executor,
    timeout_seconds=5.0,
)

book_appointment_tool = ToolDefinition(
    name="book_appointment",
    description="Book an appointment for the customer",
    category=ToolCategory.SCHEDULING,
    parameters=[
        ToolParameter(
            name="date_time",
            type="string",
            description="Date and time for appointment (ISO 8601 format)",
            required=True,
        ),
        ToolParameter(
            name="duration_minutes",
            type="integer",
            description="Duration in minutes",
            required=False,
        ),
        ToolParameter(
            name="purpose",
            type="string",
            description="Purpose of the appointment",
            required=False,
        ),
    ],
    executor=AppointmentSchedulingTool().book_appointment_executor,
    timeout_seconds=5.0,
)
```

### Conversation Flow Example

```
Caller: "I need to schedule a technician to come look at my internet"

Agent: "I can help you schedule a service appointment. What date would work 
        best for you?"

Caller: "How about tomorrow?"

[Tool Call: check_availability(date="2026-02-03", duration_minutes=60)]

Agent: "I have several openings tomorrow. I can offer you 9:00 AM, 11:30 AM, 
        2:00 PM, or 4:30 PM. Which would you prefer?"

Caller: "2:00 PM works for me"

[Tool Call: book_appointment(date_time="2026-02-03T14:00:00", duration_minutes=60, purpose="Internet service technician visit")]

Agent: "Perfect! I've scheduled your appointment for tomorrow, February 3rd 
        at 2:00 PM. A technician will arrive to diagnose and resolve your 
        internet issue. Your confirmation code is ABC123. You'll receive a 
        confirmation text shortly. Is there anything else I can help you with?"
```

## Acceptance Criteria

- [ ] Can check availability for specific dates
- [ ] Can book appointments with customer details
- [ ] Can reschedule existing appointments
- [ ] Can cancel appointments
- [ ] Sends confirmation notifications (SMS/email)
- [ ] Integrates with at least 2 calendar systems
- [ ] Prevents double-booking
- [ ] Handles timezone correctly

## Dependencies

- Authentication Tool (to verify customer identity)
- CRM Integration (to link appointments to customer records)
- SMS/Email service for confirmations

## Notes

- Consider business hours and holidays
- Support different appointment types (service, consultation, delivery)
- Allow buffer time between appointments
- Send reminder notifications 24 hours before
