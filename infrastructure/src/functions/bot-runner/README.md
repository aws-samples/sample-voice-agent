# Bot Runner Lambda Function

Python Lambda function that handles Daily dial-in webhooks and routes calls to the ECS voice service.

## Architecture

```
Daily PSTN ──> API Gateway ──> Lambda ──> Daily API (create room)
    |                             |
    |                             └──> ECS Service (POST /call)
    |                                        |
    └────────────────────────────────────────┘
              (SIP transfer to room)
```

## Components

### handler.py
Main Lambda entry point with `/start` webhook handler:
- Parses Daily dial-in webhook payload
- Validates required fields (callId, callDomain)
- Creates Daily room with SIP enabled
- Generates bot meeting token
- Calls ECS voice service to handle the call
- Returns SIP URI for call routing
- Supports both PSTN (via Daily webhook) and SIP (via direct request) modes

### daily_client.py
Daily.co REST API client:
- Room creation with SIP configuration
- Meeting token generation
- SIP URI retrieval
- API key fetched from Secrets Manager

### service_client.py
ECS Service HTTP client:
- Reads service endpoint from SSM Parameter Store
- Sends call requests (POST /call) with room config
- Health check support
- Fallback to environment variable for endpoint

### ecs_client.py
AWS ECS client for direct task management:
- Start ECS Fargate tasks with environment overrides
- Task status checking
- Task termination

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DAILY_API_KEY_SECRET_ARN` | ARN of secret containing Daily API key | Yes |
| `ECS_SERVICE_ENDPOINT` | HTTP endpoint for ECS voice service (fallback) | No |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, etc.) | No |

The ECS service endpoint is primarily read from SSM Parameter Store (`/voice-agent/ecs/service-endpoint`).

## API

### POST /start

Handle Daily dial-in webhook.

**PSTN Request (from Daily webhook):**
```json
{
  "callId": "abc123",
  "callDomain": "your-domain.daily.co",
  "from": "+15551234567",
  "to": "+15559876543",
  "direction": "inbound"
}
```

**SIP Request (direct):**
```json
{
  "source": "sip",
  "caller_id": "web-client-001",
  "caller_number": "sip:100@asterisk.local"
}
```

**Response (Success):**
```json
{
  "sessionId": "voice-abc123-a1b2c3d4",
  "roomUrl": "https://your-domain.daily.co/voice-abc123",
  "sipUri": "sip:room-id@sip.daily.co",
  "status": "started",
  "message": "Voice session started successfully"
}
```

**Response (Error):**
```json
{
  "error": "Missing required field: callId",
  "status": "error"
}
```

## Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run tests (from infrastructure directory)
pytest src/functions/bot-runner/ -v

# Set environment for local testing
export DAILY_API_KEY_SECRET_ARN=arn:aws:secretsmanager:...
```

## Deployment

The function is deployed automatically as part of the BotRunnerStack:

```bash
cd infrastructure
npm run deploy
```

## Flow Diagram

```
1. Caller dials PSTN number
2. Daily routes call to webhook endpoint
3. Lambda receives POST /start
4. Lambda creates Daily room (SIP enabled)
5. Lambda generates bot meeting token
6. Lambda calls ECS voice service (POST /call)
7. ECS service spawns pipecat pipeline
8. Pipecat joins Daily room
9. Lambda returns SIP URI to Daily
10. Daily transfers caller to room
11. Voice session begins
```

## Error Handling

| Error | HTTP Code | Cause | Resolution |
|-------|-----------|-------|------------|
| Missing callId | 400 | Webhook payload incomplete | Check Daily configuration |
| Missing callDomain | 400 | Webhook payload incomplete | Check Daily configuration |
| Daily API error | 500 | Room creation failed | Check Daily API key |
| ECS service error | 500 | Service call failed | Check ECS service health and NLB |
| Voice agent unavailable | 503 | Service at capacity | Check auto-scaling and session limits |
