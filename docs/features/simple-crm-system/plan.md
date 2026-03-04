---
started: 2026-02-02
---

# Implementation Plan: Simple CRM System

## Overview

Build a lightweight, self-hosted CRM system using DynamoDB and Lambda to provide customer context, case management, and interaction tracking for the voice agent. This eliminates external CRM dependencies while enabling sophisticated voice interactions with customer data.

**Key Goals:**
- Store customer data for personalized voice interactions
- Track support cases/tickets with full history
- Enable Knowledge-Based Authentication (KBA) for security
- Provide demo-ready scenarios for presentations
- Achieve <500ms API response times

## Implementation Steps

### Phase 1: Core Infrastructure (Week 1-2)

#### 1.1 CDK Stack Creation
- [ ] Create `infrastructure/src/stacks/crm-stack.ts` with DynamoDB tables
  - Customers table with phone-index GSI
  - Cases table with customer-index GSI
  - Interactions table for call history
- [ ] Set up Lambda function for API handling
- [ ] Configure API Gateway with proper CORS and routing
- [ ] Implement IAM roles and policies for secure access
- [ ] Add SSM parameters for cross-stack communication
- [ ] Export API URL and table names for voice agent integration

#### 1.2 Data Layer Implementation
- [ ] Create `lambda/crm-api/models/customer.py` with CRUD operations
- [ ] Create `lambda/crm-api/models/case.py` for case management
- [ ] Create `lambda/crm-api/models/interaction.py` for call history
- [ ] Implement input validation and sanitization
- [ ] Add database indexes for performance optimization
- [ ] Implement pagination for large result sets

### Phase 2: API Development (Week 2-3)

#### 2.1 REST API Implementation
- [ ] Implement `GET /customers?phone={phone}` - Search by phone
- [ ] Implement `GET /customers?email={email}` - Search by email
- [ ] Implement `GET /customers/{id}` - Get specific customer
- [ ] Implement `POST /customers` - Create new customer
- [ ] Implement `PUT /customers/{id}` - Update customer
- [ ] Implement `GET /customers/{id}/cases` - Get customer's cases
- [ ] Implement `GET /cases?customer_id={id}` - List cases
- [ ] Implement `POST /cases` - Create support case
- [ ] Implement `PUT /cases/{id}` - Update case status
- [ ] Implement `POST /cases/{id}/notes` - Add case notes
- [ ] Implement `POST /interactions` - Log call interaction
- [ ] Implement `POST /admin/seed` - Load demo data
- [ ] Implement `DELETE /admin/reset` - Clear demo data

#### 2.2 Demo Data Strategy
- [ ] Create demo customers with diverse scenarios:
  - John Smith (555-0100) - Premium customer with billing dispute
  - Sarah Johnson (555-0101) - Basic customer, no open cases
  - Michael Chen (555-0102) - Enterprise customer with urgent issue
- [ ] Include KBA data for authentication demos
- [ ] Pre-populate with realistic transaction history
- [ ] Add varied case types (billing, technical, account)

### Phase 3: Voice Agent Integration (Week 3-4)

#### 3.1 CRM Tools Development
- [ ] Create `app/tools/crm/customer_lookup_tool.py`
  - Search customers by phone/email
  - Return customer context for LLM
  - Handle fuzzy matching for phone numbers
- [ ] Create `app/tools/crm/case_management_tool.py`
  - Create new support cases from voice calls
  - Update case status and add notes
  - Link cases to voice sessions
- [ ] Create `app/tools/crm/verification_tool.py`
  - Knowledge-based authentication questions
  - Verify account numbers and recent transactions
  - Track verification status
- [ ] Create `app/tools/crm/interaction_logger_tool.py`
  - Log conversation start/end
  - Track call outcomes and resolution
  - Store transcript summaries

#### 3.2 Service Layer
- [ ] Create `app/services/crm_service.py` as HTTP client
  - Async methods for all API operations
  - Error handling and retry logic
  - Circuit breaker pattern for resilience
- [ ] Add environment variables:
  - `CRM_API_URL` - API Gateway endpoint
  - `CRM_TIMEOUT_SECONDS` - Request timeout (default: 5)
  - `ENABLE_CRM_TOOLS` - Feature flag
- [ ] Integrate with existing tool registry

### Phase 4: Testing & Optimization (Week 4-5)

#### 4.1 Testing Strategy
- [ ] Unit tests for Lambda handlers (>90% coverage)
- [ ] Unit tests for CRM tools in voice agent
- [ ] Integration tests for API endpoints
- [ ] End-to-end tests for voice agent scenarios
- [ ] Load tests for 100 concurrent users
- [ ] Performance validation (<500ms response time)

#### 4.2 Performance Optimization
- [ ] DynamoDB query optimization with proper indexes
- [ ] Lambda cold start reduction (provisioned concurrency if needed)
- [ ] API response caching for frequently accessed data
- [ ] Connection pooling for HTTP client

### Phase 5: Deployment & Monitoring (Week 5-6)

#### 5.1 Deployment Pipeline
- [ ] Add CRM stack to CDK deployment
- [ ] Configure CI/CD pipeline for Lambda deployments
- [ ] Implement automated demo data seeding
- [ ] Create rollback procedures

#### 5.2 Observability
- [ ] CloudWatch metrics for API latency
- [ ] Error rate monitoring and alerting
- [ ] Customer lookup success rate tracking
- [ ] Voice agent tool execution metrics
- [ ] Dashboard for CRM system health

## Technical Decisions

### Architecture
- **DynamoDB**: Single-table design for Customers and Cases with GSIs for flexible querying
- **Lambda + API Gateway**: Serverless architecture for cost-effective, pay-per-use model
- **Python**: Consistent with existing voice agent codebase
- **Async HTTP**: aiohttp for non-blocking CRM API calls from voice agent

### Data Model
- **Customer ID**: UUID v4 for global uniqueness
- **Case ID**: TICKET-YYYY-XXXXX format for human readability
- **Phone Index**: GSI for primary lookup by phone number (most common search)
- **Soft Deletes**: Use status fields rather than hard deletes for audit trail

### Security
- **IAM Roles**: Least-privilege access for Lambda functions
- **API Gateway**: Throttling and request validation
- **Data Masking**: PII redaction in logs
- **Encryption**: DynamoDB encryption at rest (AWS managed)

### Integration
- **Environment-Based**: CRM_API_URL configured per environment
- **Feature Flags**: ENABLE_CRM_TOOLS for gradual rollout
- **Circuit Breaker**: Fail gracefully if CRM is unavailable
- **Timeouts**: 5-second timeout to prevent blocking voice agent

## Testing Strategy

### Unit Tests
- Lambda handler input/output validation
- Data model CRUD operations
- Tool execution logic
- Error handling paths

### Integration Tests
- API endpoint contract validation
- DynamoDB read/write operations
- Voice agent tool integration
- Demo data seeding/reset

### End-to-End Tests
- Complete voice agent conversation flows
- Customer lookup → authentication → case creation
- Demo scenario validation
- Performance benchmarks

### Load Tests
- 100 concurrent API requests
- Voice agent with 50 simultaneous calls
- DynamoDB throughput validation

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| API latency affects voice agent | High | Async calls, <500ms SLA, circuit breaker |
| Data corruption during demos | Medium | Automated reset, backup/restore procedures |
| DynamoDB throttling | Medium | On-demand capacity, proper indexing |
| PII exposure in logs | High | Data masking, encryption, access controls |
| Voice agent performance degradation | High | Feature flags, fallback to mock data |
| Concurrent update conflicts | Medium | Optimistic locking, conditional writes |

## Dependencies

### Infrastructure
- DynamoDB (existing AWS account)
- Lambda runtime (Python 3.11)
- API Gateway
- IAM for permissions

### Application
- Existing tool registry framework
- aiohttp for async HTTP
- Environment variable configuration

### External
- None (self-hosted solution)

## Success Criteria

- [ ] All API endpoints functional with <500ms response time
- [ ] Voice agent tools successfully integrated
- [ ] Demo data provides compelling scenarios
- [ ] Unit test coverage >90%
- [ ] Zero PII exposure in logs
- [ ] 99.9% uptime during demos
- [ ] Successful authentication flow with KBA
- [ ] Case creation and tracking works end-to-end

## Future Enhancements (Post-MVP)

- Web UI for CRM data management
- Advanced analytics dashboard
- Integration with external notification systems
- Real-time case status updates
- Multi-tenant support for different demo scenarios
