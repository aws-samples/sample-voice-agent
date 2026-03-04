---
id: order-management-tool
name: Order Management Tool
type: Feature
priority: P2
effort: Medium
impact: Medium
created: 2026-02-02
---

# Order Management Tool

## Problem Statement

Customers frequently call to check order status, track shipments, modify orders, or process returns. Without direct access to order management systems, these routine inquiries require human agent assistance.

## Proposed Solution

Create an order management tool that integrates with e-commerce and order management systems to provide self-service order capabilities.

### Supported Systems

1. **Shopify** - Popular e-commerce platform
2. **Magento/Adobe Commerce** - Enterprise e-commerce
3. **WooCommerce** - WordPress-based stores
4. **Custom OMS** - Generic REST API connector

### Tools to Implement

1. **`check_order_status`** - Get current status and tracking info
2. **`track_shipment`** - Get real-time shipping updates
3. **`modify_order`** - Change items, quantities, or shipping
4. **`cancel_order`** - Cancel unshipped orders
5. **`process_return`** - Initiate return/exchange
6. **`get_order_history`** - List recent orders

### Technical Design

```python
# app/tools/builtin/order_tools.py

from app.tools import ToolDefinition, ToolParameter, ToolCategory, success_result, error_result
from app.services.order_service import OrderServiceFactory

class OrderManagementTool:
    """Unified order management interface."""
    
    def __init__(self):
        self.order_service = OrderServiceFactory.get_order_service()
    
    async def check_order_status_executor(self, arguments: dict, context: ToolContext) -> ToolResult:
        """Check order status and tracking."""
        order_id = arguments.get("order_id")
        
        # Verify customer owns this order
        customer_id = context.get_customer_id()
        
        try:
            order = await self.order_service.get_order(order_id)
            
            # Security check: verify order belongs to customer
            if order["customer_id"] != customer_id:
                return error_result("Order not found or access denied")
            
            return success_result({
                "order_id": order["id"],
                "status": order["status"],
                "order_date": order["created_at"],
                "items": order["items"],
                "total": order["total"],
                "shipping_address": order["shipping_address"],
                "estimated_delivery": order.get("estimated_delivery"),
                "tracking_number": order.get("tracking_number"),
                "tracking_url": order.get("tracking_url"),
            })
        except Exception as e:
            return error_result(f"Failed to retrieve order: {str(e)}")
    
    async def track_shipment_executor(self, arguments: dict, context: ToolContext) -> ToolResult:
        """Get real-time tracking updates."""
        tracking_number = arguments.get("tracking_number")
        carrier = arguments.get("carrier")
        
        try:
            tracking = await self.order_service.track_shipment(
                tracking_number=tracking_number,
                carrier=carrier,
            )
            return success_result({
                "tracking_number": tracking_number,
                "carrier": carrier,
                "status": tracking["status"],
                "current_location": tracking.get("current_location"),
                "estimated_delivery": tracking.get("estimated_delivery"),
                "events": tracking.get("events", []),
            })
        except Exception as e:
            return error_result(f"Failed to track shipment: {str(e)}")
    
    async def process_return_executor(self, arguments: dict, context: ToolContext) -> ToolResult:
        """Initiate return/exchange."""
        order_id = arguments.get("order_id")
        items = arguments.get("items", [])  # List of items to return
        reason = arguments.get("reason", "")
        
        try:
            return_request = await self.order_service.create_return(
                order_id=order_id,
                customer_id=context.get_customer_id(),
                items=items,
                reason=reason,
            )
            return success_result({
                "return_initiated": True,
                "return_id": return_request["id"],
                "return_label_url": return_request.get("label_url"),
                "refund_amount": return_request.get("refund_amount"),
                "instructions": return_request.get("instructions"),
            })
        except Exception as e:
            return error_result(f"Failed to process return: {str(e)}")

# Tool Definitions
check_order_status_tool = ToolDefinition(
    name="check_order_status",
    description="Check the status of an order by order ID",
    category=ToolCategory.ORDERS,
    parameters=[
        ToolParameter(
            name="order_id",
            type="string",
            description="Order number or ID",
            required=True,
        ),
    ],
    executor=OrderManagementTool().check_order_status_executor,
    timeout_seconds=5.0,
)

track_shipment_tool = ToolDefinition(
    name="track_shipment",
    description="Track a shipment by tracking number",
    category=ToolCategory.ORDERS,
    parameters=[
        ToolParameter(
            name="tracking_number",
            type="string",
            description="Shipping tracking number",
            required=True,
        ),
        ToolParameter(
            name="carrier",
            type="string",
            description="Shipping carrier (UPS, FedEx, USPS, etc.)",
            required=False,
        ),
    ],
    executor=OrderManagementTool().track_shipment_executor,
    timeout_seconds=5.0,
)

process_return_tool = ToolDefinition(
    name="process_return",
    description="Initiate a return or exchange for an order",
    category=ToolCategory.ORDERS,
    parameters=[
        ToolParameter(
            name="order_id",
            type="string",
            description="Order ID",
            required=True,
        ),
        ToolParameter(
            name="items",
            type="array",
            description="List of items to return (item IDs or descriptions)",
            required=True,
        ),
        ToolParameter(
            name="reason",
            type="string",
            description="Reason for return",
            required=False,
        ),
    ],
    executor=OrderManagementTool().process_return_executor,
    timeout_seconds=5.0,
)
```

### Conversation Flow Example

```
Caller: "Where's my order?"

Agent: "I can help you track your order. Could you provide your order number?"

Caller: "It's ORD-123456"

[Tool Call: check_order_status(order_id="ORD-123456")]

Agent: "I found your order from January 28th. It contains 2 items totaling $89.99. 
        Your order shipped yesterday via UPS and is currently in transit. 
        The estimated delivery is February 4th. Would you like the tracking number?"

Caller: "Yes, and can I return one of the items?"

Agent: "Your tracking number is 1Z999AA10123456784. You can track it at 
        ups.com/track. Regarding the return, which item would you like to return?"

Caller: "The blue shirt, size medium"

[Tool Call: process_return(order_id="ORD-123456", items=["Blue Shirt - Medium"], reason="Wrong size")]

Agent: "I've initiated a return for the Blue Shirt, size medium. You'll receive 
        a return label via email within 15 minutes. Once we receive the item, 
        you'll be refunded $34.99 to your original payment method. Is there 
        anything else I can help you with?"
```

## Acceptance Criteria

- [ ] Can check order status and details
- [ ] Can track shipments with real-time updates
- [ ] Can modify unshipped orders
- [ ] Can cancel unshipped orders
- [ ] Can initiate returns/exchanges
- [ ] Can view order history
- [ ] Integrates with at least 2 e-commerce platforms
- [ ] Security: customers can only access their own orders
- [ ] Handles order not found gracefully

## Dependencies

- Authentication Tool (medium level required)
- CRM Integration (to link orders to customers)
- Shipping carrier APIs (UPS, FedEx, USPS)

## Notes

- Support partial returns (some items from order)
- Handle exchange requests (return + new order)
- Consider return policy rules (time limits, condition requirements)
- Send confirmation emails for all actions
- Track return status separately from orders
