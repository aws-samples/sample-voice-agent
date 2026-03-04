---
id: simple-crm-system
name: Simple CRM System
type: Infrastructure
priority: P1
effort: Medium
impact: High
created: 2026-02-02
---

# Simple CRM System

## Problem Statement

Rather than integrating with complex external CRM platforms (Salesforce, HubSpot), we need a lightweight, self-hosted CRM system for the POC that:
- Stores customer data for voice agent interactions
- Tracks cases/tickets
- Requires no external dependencies or licenses
- Can be easily populated with demo data
- Uses existing AWS infrastructure (DynamoDB)

## Proposed Solution

Build a simple CRM using DynamoDB tables with a lightweight REST API. This provides full control over the data model while leveraging existing infrastructure.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Simple CRM System                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              REST API (Lambda/API Gateway)            │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │  │
│  │  │  GET     │  │  POST    │  │  PUT     │          │  │
│  │  │/customers│  │/customers│  │/cases    │          │  │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘          │  │
│  └───────┼─────────────┼─────────────┼────────────────┘  │
│          │             │             │                    │
│          └─────────────┴─────────────┘                    │
│                        │                                   │
│                        ▼                                   │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                    DynamoDB Tables                    │  │
│  │  ┌─────────────────┐  ┌─────────────────┐            │  │
│  │  │   Customers     │  │     Cases       │            │  │
│  │  │  - customer_id  │  │  - case_id      │            │  │
│  │  │  - phone        │  │  - customer_id  │            │  │
│  │  │  - email        │  │  - subject      │            │  │
│  │  │  - name         │  │  - status       │            │  │
│  │  │  - account_type │  │  - priority     │            │  │
│  │  │  - created_at   │  │  - created_at   │            │  │
│  │  └─────────────────┘  └─────────────────┘            │  │
│  │  ┌─────────────────┐  ┌─────────────────┐            │  │
│  │  │  Interactions   │  │   Activities    │            │  │
│  │  │  - call_history │  │  - orders       │            │  │
│  │  │  - notes        │  │  - payments     │            │  │
│  │  └─────────────────┘  └─────────────────┘            │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Data Model

#### Customers Table
```typescript
interface Customer {
  customer_id: string;          // UUID or auto-generated
  phone: string;                // Primary lookup key
  email: string;
  first_name: string;
  last_name: string;
  account_type: "basic" | "premium" | "enterprise";
  account_status: "active" | "suspended" | "closed";
  member_since: string;         // ISO date
  address?: {
    street: string;
    city: string;
    state: string;
    zip: string;
  };
  preferences?: {
    contact_method: "phone" | "email";
    language: string;
  };
  // For KBA (Knowledge-Based Authentication)
  account_last4?: string;
  recent_transaction?: {
    date: string;
    amount: number;
    merchant: string;
  };
  created_at: string;
  updated_at: string;
}
```

#### Cases Table
```typescript
interface Case {
  case_id: string;              // TICKET-YYYY-XXXXX format
  customer_id: string;          // Foreign key to Customers
  subject: string;
  description: string;
  status: "open" | "in_progress" | "pending" | "resolved" | "closed";
  priority: "low" | "medium" | "high" | "urgent";
  category: "billing" | "technical" | "account" | "order" | "general";
  assigned_to?: string;         // Agent ID or null
  created_at: string;
  updated_at: string;
  resolved_at?: string;
  notes: Array<{
    timestamp: string;
    author: string;
    content: string;
  }>;
  // Link to voice session if created from call
  session_id?: string;
  transcript_summary?: string;
}
```

#### Interactions Table (Call History)
```typescript
interface Interaction {
  interaction_id: string;
  customer_id: string;
  session_id: string;           // Link to voice agent session
  type: "call" | "chat" | "email";
  start_time: string;
  duration_seconds: number;
  status: "completed" | "transferred" | "abandoned";
  intent?: string;              // Detected intent
  sentiment?: "positive" | "neutral" | "negative";
  resolved: boolean;
  notes?: string;
  agent_id?: string;            // If transferred to human
}
```

### API Endpoints

#### Customers
```
GET    /customers?phone={phone}           # Search by phone
GET    /customers?email={email}           # Search by email
GET    /customers/{customer_id}           # Get specific customer
POST   /customers                         # Create new customer
PUT    /customers/{customer_id}           # Update customer
GET    /customers/{id}/cases              # Get customer's cases
GET    /customers/{id}/interactions       # Get customer's call history
```

#### Cases
```
GET    /cases?customer_id={id}&status=open # List cases
GET    /cases/{case_id}                   # Get specific case
POST   /cases                             # Create case
PUT    /cases/{case_id}                   # Update case
POST   /cases/{case_id}/notes             # Add note to case
```

#### Demo Data
```
POST   /admin/seed                        # Load demo data
DELETE /admin/reset                       # Clear all data
```

### Implementation

#### CDK Infrastructure

```typescript
// infrastructure/src/stacks/crm-stack.ts

export class SimpleCRMStack extends cdk.Stack {
  constructor(scope: cdk.App, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // DynamoDB Tables
    const customersTable = new dynamodb.Table(this, 'CustomersTable', {
      tableName: 'voice-agent-customers',
      partitionKey: { name: 'customer_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'phone', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // GSI for phone lookups
    customersTable.addGlobalSecondaryIndex({
      indexName: 'phone-index',
      partitionKey: { name: 'phone', type: dynamodb.AttributeType.STRING },
    });

    const casesTable = new dynamodb.Table(this, 'CasesTable', {
      tableName: 'voice-agent-cases',
      partitionKey: { name: 'case_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'customer_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
    });

    // GSI for customer case lookups
    casesTable.addGlobalSecondaryIndex({
      indexName: 'customer-index',
      partitionKey: { name: 'customer_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'created_at', type: dynamodb.AttributeType.STRING },
    });

    // Lambda Function for API
    const crmApiFunction = new lambda.Function(this, 'CRMApiFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'index.handler',
      code: lambda.Code.fromAsset('lambda/crm-api'),
      environment: {
        CUSTOMERS_TABLE: customersTable.tableName,
        CASES_TABLE: casesTable.tableName,
      },
    });

    customersTable.grantReadWriteData(crmApiFunction);
    casesTable.grantReadWriteData(crmApiFunction);

    // API Gateway
    const api = new apigw.RestApi(this, 'CRMApi', {
      restApiName: 'Voice Agent CRM API',
    });

    const customersResource = api.root.addResource('customers');
    customersResource.addMethod('GET', new apigw.LambdaIntegration(crmApiFunction));
    customersResource.addMethod('POST', new apigw.LambdaIntegration(crmApiFunction));

    // ... more routes
  }
}
```

#### Lambda Handler (Python)

```python
# lambda/crm-api/index.py

import json
import boto3
import uuid
from datetime import datetime
from typing import Dict, Any

dynamodb = boto3.resource('dynamodb')
customers_table = dynamodb.Table(os.environ['CUSTOMERS_TABLE'])
cases_table = dynamodb.Table(os.environ['CASES_TABLE'])

def handler(event, context):
    """Main Lambda handler for CRM API."""
    method = event['httpMethod']
    path = event['path']
    
    if method == 'GET' and '/customers' in path:
        return handle_get_customers(event)
    elif method == 'POST' and '/customers' in path:
        return handle_create_customer(event)
    elif method == 'GET' and '/cases' in path:
        return handle_get_cases(event)
    elif method == 'POST' and '/cases' in path:
        return handle_create_case(event)
    elif method == 'POST' and '/admin/seed' in path:
        return handle_seed_data(event)
    
    return {
        'statusCode': 404,
        'body': json.dumps({'error': 'Not found'})
    }

def handle_get_customers(event):
    """Search customers by phone or email."""
    params = event.get('queryStringParameters', {}) or {}
    
    if 'phone' in params:
        # Query by phone using GSI
        response = customers_table.query(
            IndexName='phone-index',
            KeyConditionExpression='phone = :phone',
            ExpressionAttributeValues={':phone': params['phone']}
        )
        return {
            'statusCode': 200,
            'body': json.dumps(response['Items'])
        }
    
    # ... handle other search params

def handle_create_customer(event):
    """Create new customer."""
    body = json.loads(event['body'])
    
    customer = {
        'customer_id': str(uuid.uuid4()),
        'phone': body['phone'],
        'email': body.get('email'),
        'first_name': body['first_name'],
        'last_name': body['last_name'],
        'account_type': body.get('account_type', 'basic'),
        'account_status': 'active',
        'member_since': datetime.now().isoformat(),
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat(),
        # KBA data
        'account_last4': body.get('account_last4'),
        'recent_transaction': body.get('recent_transaction'),
    }
    
    customers_table.put_item(Item=customer)
    
    return {
        'statusCode': 201,
        'body': json.dumps(customer)
    }

def handle_seed_data(event):
    """Load demo data for testing."""
    demo_customers = [
        {
            'customer_id': 'cust-001',
            'phone': '555-0100',
            'email': 'john.smith@example.com',
            'first_name': 'John',
            'last_name': 'Smith',
            'account_type': 'premium',
            'account_status': 'active',
            'member_since': '2022-03-15T00:00:00Z',
            'account_last4': '4567',
            'recent_transaction': {
                'date': '2026-01-28',
                'amount': 89.99,
                'merchant': 'TechStore Online'
            },
        },
        # ... more demo customers
    ]
    
    for customer in demo_customers:
        customers_table.put_item(Item=customer)
    
    return {
        'statusCode': 200,
        'body': json.dumps({'message': f'Seeded {len(demo_customers)} customers'})
    }
```

### Voice Agent Integration

The CRM tools will call this simple API instead of external CRMs:

```python
# app/services/simple_crm_service.py

import aiohttp
import os

class SimpleCRMService:
    """Client for the simple CRM API."""
    
    def __init__(self):
        self.base_url = os.environ.get('CRM_API_URL')
    
    async def search_customer(self, phone: str) -> Optional[dict]:
        """Search for customer by phone."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/customers",
                params={"phone": phone}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data[0] if data else None
                return None
    
    async def get_customer_cases(self, customer_id: str) -> list:
        """Get customer's open cases."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/customers/{customer_id}/cases"
            ) as response:
                if response.status == 200:
                    return await response.json()
                return []
    
    async def create_case(self, customer_id: str, case_data: dict) -> dict:
        """Create a support case."""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/cases",
                json={
                    "customer_id": customer_id,
                    **case_data
                }
            ) as response:
                return await response.json()
```

### Demo Data

Pre-populate with realistic demo customers:

```python
DEMO_CUSTOMERS = [
    {
        "phone": "555-0100",
        "name": "John Smith",
        "account_type": "premium",
        "member_since": "2022-03-15",
        "account_last4": "4567",
        "recent_transaction": {"date": "2026-01-28", "amount": 89.99, "merchant": "TechStore"},
        "open_cases": [
            {
                "case_id": "TICKET-2026-0001",
                "subject": "Billing dispute - October charge",
                "status": "open",
                "priority": "high"
            }
        ]
    },
    {
        "phone": "555-0101",
        "name": "Sarah Johnson",
        "account_type": "basic",
        "member_since": "2024-01-10",
        "account_last4": "8901",
        "recent_transaction": {"date": "2026-01-30", "amount": 45.50, "merchant": "Coffee Corner"},
        "open_cases": []
    },
    {
        "phone": "555-0102",
        "name": "Michael Chen",
        "account_type": "enterprise",
        "member_since": "2020-11-20",
        "account_last4": "2345",
        "recent_transaction": {"date": "2026-01-29", "amount": 1250.00, "merchant": "Enterprise Solutions"},
        "open_cases": [
            {
                "case_id": "TICKET-2026-0002",
                "subject": "Service outage - API connectivity",
                "status": "in_progress",
                "priority": "urgent"
            }
        ]
    },
]
```

## Why It Matters

- **No External Dependencies**: Self-hosted, no API keys or licenses needed
- **Fast Development**: Simple data model, quick to implement
- **Full Control**: Modify schema as needed for demos
- **Cost Effective**: Uses existing DynamoDB, pay-per-use Lambda
- **Demo Ready**: Easy to seed with compelling demo scenarios
- **Scalable**: Can migrate to real CRM later if needed

## Acceptance Criteria

- [ ] DynamoDB tables for Customers, Cases, and Interactions
- [ ] REST API with search by phone/email
- [ ] Lambda function to handle API requests
- [ ] API Gateway for HTTP endpoints
- [ ] Demo data seeding endpoint
- [ ] Integration with voice agent tools
- [ ] Response time < 500ms
- [ ] Basic error handling and validation

## Dependencies

- DynamoDB (existing)
- API Gateway
- Lambda
- IAM roles for permissions

## Notes

- Keep schema simple - only fields needed for voice agent
- Include KBA data for authentication demos
- Pre-populate with diverse scenarios (billing issues, tech support, etc.)
- Consider adding a simple web UI for viewing/managing data
- Can export/import data for backup
