# Deployment Guide

Complete guide for deploying the SIP Voice Agent. Choose your deployment mode:

- **[Cloud API Mode](#path-a-cloud-api-mode)** -- Uses Deepgram and Cartesia cloud APIs. Simpler setup, no GPU quotas or Marketplace subscriptions needed. Best for getting started and development.
- **[SageMaker Mode](#path-b-sagemaker-mode)** -- Runs Deepgram STT/TTS on self-hosted SageMaker GPU endpoints. Audio stays in your VPC. Best for production workloads with data residency requirements.

Both modes use the same core infrastructure (VPC, ECS, Lambda, API Gateway) and differ only in how STT/TTS is handled.

---

## Prerequisites (Both Modes)

### AWS Account Setup

1. **AWS Account** with administrative access
2. **AWS CLI** installed and configured with credentials:
   ```bash
   aws sts get-caller-identity  # Verify credentials work
   ```
3. **Node.js 18+** installed (check with `node --version`)
4. **Docker** installed and running (or [finch](https://github.com/runfinch/finch) as an alternative)

### Bedrock Model Access

Enable Claude models in your AWS account:

1. Go to **AWS Console** -> **Amazon Bedrock** -> **Model access**
2. Request access to:
   - `anthropic.claude-3-5-haiku-20241022`
   - `anthropic.claude-3-haiku-20240307`
3. Wait for approval (usually instant for these models)

### Daily.co Account

1. Create an account at [dashboard.daily.co](https://dashboard.daily.co)
2. Add a credit card (required for purchasing phone numbers)
3. Go to **Developers** -> **API Keys** and generate an API key
4. Save the API key -- you'll need it for secrets configuration

---

## Path A: Cloud API Mode

This mode uses Deepgram and Cartesia cloud APIs for STT/TTS. No SageMaker endpoints, no GPU quotas, no Marketplace subscriptions.

### Additional Prerequisites (Cloud API Mode)

You will need API keys for:
- **[Deepgram](https://console.deepgram.com/)** -- Speech-to-Text (Nova-3 model)
- **[Cartesia](https://play.cartesia.ai/)** -- Text-to-Speech (Sonic model)

### Step 1: Configure Environment

```bash
cd infrastructure

# Copy the environment template
cp .env.example .env
```

Edit `.env` with your settings:
```bash
# .env
ENVIRONMENT=poc
AWS_REGION=us-east-1

# Leave the Deepgram model package ARNs as-is (not needed in cloud API mode)
```

### Step 2: Install Dependencies and Deploy Foundation

```bash
# Install CDK dependencies
npm install

# Deploy foundation stacks first (Network + Storage)
USE_CLOUD_APIS=true npx cdk deploy VoiceAgentNetwork VoiceAgentStorage --require-approval never
```

This creates the VPC and Secrets Manager (~3-5 minutes).

### Step 3: Configure Secrets

Add your API keys to Secrets Manager **before deploying ECS**, so the container picks them up on first boot:

```bash
# Create backend/voice-agent/.env with your keys:
cat > ../backend/voice-agent/.env << 'EOF'
DEEPGRAM_API_KEY=your-deepgram-api-key
CARTESIA_API_KEY=your-cartesia-api-key
DAILY_API_KEY=your-daily-api-key
EOF

# Push to Secrets Manager
./scripts/init-secrets.sh

# Or run interactively (prompts for keys):
./scripts/init-secrets.sh
```

### Step 4: Deploy Remaining Stacks

```bash
# Deploy SageMaker stub + ECS + BotRunner
USE_CLOUD_APIS=true npx cdk deploy VoiceAgentSageMaker VoiceAgentEcs VoiceAgentBotRunner --require-approval never
```

The ECS container starts with real API keys on first boot. No forced redeployment needed.

This deploys 3 remaining stacks:
1. **VoiceAgentSageMaker** -- Stub stack (placeholder SSM parameters only in cloud API mode)
2. **VoiceAgentEcs** -- ECS Fargate cluster, NLB, CloudWatch dashboard
3. **VoiceAgentBotRunner** -- Lambda webhook handler, API Gateway

Total deployment time: ~8-10 minutes.

### Step 5: Set Up Daily.co Phone Number

Purchase a phone number and configure the webhook:

```bash
# Automated setup (recommended)
./scripts/setup-daily.sh

# Or specify a region for the phone number
PHONE_REGION=NY ./scripts/setup-daily.sh
```

The script will:
1. Load your `DAILY_API_KEY` from `backend/voice-agent/.env`
2. Fetch the webhook URL from SSM (deployed in Step 2)
3. List available phone numbers and purchase one (with confirmation)
4. Configure pinless dial-in with your webhook URL
5. Save `DAILY_PHONE_NUMBER` and `DAILY_HMAC_SECRET` to `.env`

After running, sync the updated secrets to AWS:
```bash
./scripts/init-secrets.sh
```

For manual setup or troubleshooting, see [Daily.co Setup Guide](../docs/reference/daily-setup.md).

> **Note:** It can take a few minutes for Daily.co to fully provision the phone number and activate dial-in routing. If the first call doesn't connect, wait 2-3 minutes and try again.

### Step 6: Verify and Test

```bash
# Test the webhook endpoint
./deploy.sh webhook

# Or run the full integration test suite
./deploy.sh verify
```

Then **call your phone number** -- you should hear the voice assistant respond.

---

## Path B: SageMaker Mode

This mode runs Deepgram STT/TTS on dedicated SageMaker GPU endpoints inside your VPC. Audio never leaves AWS.

### Additional Prerequisites (SageMaker Mode)

#### Service Quotas

Request these quotas in the [Service Quotas console](https://console.aws.amazon.com/servicequotas/) before deployment:

| Service | Quota | Value Needed |
|---------|-------|--------------|
| SageMaker | ml.g6.2xlarge for endpoint usage | 2+ |
| SageMaker | ml.g6.12xlarge for endpoint usage | 2+ |
| VPC | Elastic IPs | 2+ |
| VPC | NAT Gateways per AZ | 1+ |

Quota increases can take 24-48 hours for GPU instances.

#### Deepgram Marketplace Subscriptions

Subscribe to Deepgram model packages on AWS Marketplace. See the [Deepgram Marketplace Setup Guide](../docs/reference/deepgram-marketplace-setup.md) for detailed step-by-step instructions.

After subscribing, you will have two model package ARNs:
- **STT**: `arn:aws:sagemaker:<region>:865070037744:model-package/deepgram-streaming-stt-...`
- **TTS**: `arn:aws:sagemaker:<region>:865070037744:model-package/deepgram-streaming-tts-...`

### Step 1: Configure Environment

```bash
cd infrastructure

# Copy the environment template
cp .env.example .env
```

Edit `.env` with your settings:
```bash
# .env
ENVIRONMENT=poc
AWS_REGION=us-east-1

# Deepgram Model Package ARNs (from Marketplace subscription)
DEEPGRAM_STT_MODEL_PACKAGE_ARN=arn:aws:sagemaker:us-east-1:865070037744:model-package/deepgram-streaming-stt-...
DEEPGRAM_TTS_MODEL_PACKAGE_ARN=arn:aws:sagemaker:us-east-1:865070037744:model-package/deepgram-streaming-tts-...
```

### Step 2: Install Dependencies and Deploy Foundation

```bash
# Install CDK dependencies
npm install

# Deploy foundation stacks first (Network + Storage)
npx cdk deploy VoiceAgentNetwork VoiceAgentStorage --require-approval never
```

### Step 3: Configure Secrets

Add your Daily API key to Secrets Manager **before deploying ECS**:

```bash
# Create backend/voice-agent/.env with your Daily API key
cat > ../backend/voice-agent/.env << 'EOF'
DAILY_API_KEY=your-daily-api-key
EOF

# Push to Secrets Manager
./scripts/init-secrets.sh
```

In SageMaker mode, you only need the `DAILY_API_KEY`. Deepgram and Cartesia keys are not needed because STT/TTS runs on SageMaker endpoints within your VPC.

### Step 4: Deploy Remaining Stacks

```bash
# Deploy SageMaker endpoints + ECS + BotRunner
npx cdk deploy VoiceAgentSageMaker VoiceAgentEcs VoiceAgentBotRunner --require-approval never
```

This deploys 3 remaining stacks:
1. **VoiceAgentSageMaker** -- Deepgram STT + TTS SageMaker endpoints (~15 minutes)
2. **VoiceAgentEcs** -- ECS Fargate cluster, NLB, CloudWatch dashboard
3. **VoiceAgentBotRunner** -- Lambda webhook handler, API Gateway

Total deployment time: ~20-25 minutes (SageMaker endpoint provisioning is the bottleneck).

### Step 5: Set Up Daily.co Phone Number

Same as Cloud API mode:
```bash
./scripts/setup-daily.sh
./scripts/init-secrets.sh
```

### Step 6: Verify and Test

```bash
./deploy.sh verify
```

Call your phone number to test.

---

## Post-Deployment Options

### Deploy Capability Agents (A2A)

The Knowledge Base and CRM capability agents extend the voice agent with RAG and customer data. They are optional.

```bash
# Deploy Knowledge Base agent
./deploy.sh deploy-stack VoiceAgentKnowledgeBase
./deploy.sh deploy-stack VoiceAgentKbAgent

# Deploy CRM agent
./deploy.sh deploy-stack VoiceAgentCRM
./deploy.sh deploy-stack VoiceAgentCrmAgent
```

Enable the capability registry so the voice agent discovers these agents:
```bash
aws ssm put-parameter \
  --name "/voice-agent/config/enable-capability-registry" \
  --value "true" \
  --type String \
  --overwrite
```

After enabling, the voice agent discovers capability agents on its next CloudMap poll cycle (default: 30 seconds). See [Adding a Capability Agent](../docs/guides/adding-a-capability-agent.md) for building custom agents.

### Enable Call Transfers

The voice agent can transfer calls to human agents via SIP REFER. See [Call Transfers](../docs/reference/call-transfers.md) for setup instructions.

### Enable Tool Calling

By default, tool calling is disabled. Enable it via SSM:
```bash
aws ssm put-parameter \
  --name "/voice-agent/config/enable-tool-calling" \
  --value "true" \
  --type String \
  --overwrite
```

This enables built-in tools (time, hangup) and any capability agent tools.

---

## Auto-Scaling Configuration

The ECS service auto-scales based on `SessionsPerTask` (average active voice calls per container).

| Parameter | Default | CDK Context | Env Var | Description |
|-----------|---------|-------------|---------|-------------|
| `minCapacity` | `1` | `-c voice-agent:minCapacity=2` | `MIN_CAPACITY` | Minimum ECS tasks (always running) |
| `maxCapacity` | `12` | `-c voice-agent:maxCapacity=20` | `MAX_CAPACITY` | Maximum ECS tasks |
| `targetSessionsPerTask` | `3` | `-c voice-agent:targetSessionsPerTask=2` | `TARGET_SESSIONS_PER_TASK` | Target tracking metric (validated 1-10) |
| `sessionCapacityPerTask` | `10` | `-c voice-agent:sessionCapacityPerTask=8` | `SESSION_CAPACITY_PER_TASK` | Per-container capacity limit (validated 1-50) |

Example:
```bash
npx cdk deploy VoiceAgentEcs \
  -c voice-agent:minCapacity=2 \
  -c voice-agent:maxCapacity=20 \
  -c voice-agent:targetSessionsPerTask=2
```

Each container supports up to `sessionCapacityPerTask` concurrent voice calls. When at capacity, the `/ready` endpoint returns 503, causing the NLB to stop routing new calls to that container.

### Scaling Policies

| Policy | Trigger | Action |
|--------|---------|--------|
| **Target Tracking** | `SessionsPerTask` deviates from target | Proportional scale-out (scale-in disabled) |
| **Burst Step Scaling** | >target+0.5 sessions/task | +10 tasks; >target+1.0 adds +25 tasks |
| **Scale-In Step Scaling** | <1.0 sessions/task for 3 periods | Remove 2 tasks (300s cooldown) |

Tasks with active voice calls are protected from termination via ECS Task Scale-in Protection.

---

## Updating the Deployment

### Update Infrastructure

```bash
cd infrastructure
./deploy.sh diff    # Preview changes
./deploy.sh deploy  # Apply changes
```

### Update Voice Agent Container

The container is built from `backend/voice-agent/Dockerfile` as a CDK Docker image asset. To update:

```bash
cd infrastructure
npx cdk deploy VoiceAgentEcs
```

CDK automatically rebuilds and pushes the container image when source files change, then triggers an ECS service update.

---

## Cleanup

To destroy all resources:

```bash
cd infrastructure
./deploy.sh destroy
```

**Warning**: This deletes all resources including VPC, SageMaker endpoints, secrets, and data.

---

## Troubleshooting

### CDK Bootstrap Failed

```bash
# Get your account ID and region
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=$(aws configure get region)

# Manually bootstrap
npx cdk bootstrap aws://${AWS_ACCOUNT}/${AWS_REGION}
```

### SageMaker Endpoint Stuck in "Creating"

1. Check CloudWatch logs: `/aws/sagemaker/Endpoints/*`
2. Verify the model package ARN is correct (from your Marketplace subscription)
3. Confirm GPU quota is available in your region
4. SageMaker endpoints typically take 10-15 minutes to provision

### No Response When Calling

1. Check Lambda logs for webhook errors (CloudWatch -> Log Groups -> search "BotRunner")
2. Verify API keys are populated in Secrets Manager (not "PLACEHOLDER")
3. Check ECS service is running: `aws ecs describe-services --cluster <cluster-name> --services <service-name>`
4. Verify Daily webhook is configured: check `setup-daily.sh` output

### High Latency

1. Check SageMaker endpoint CloudWatch metrics (if SageMaker mode)
2. Review `VoiceAgent/Pipeline` namespace for `E2ELatency` metric
3. Verify VPC endpoints are configured correctly (network stack)
4. In cloud API mode, check Deepgram/Cartesia service status pages

### No Audio Output

1. Verify Daily room configuration (SIP must be enabled)
2. Check TTS API key is valid (Cartesia in cloud mode, or SageMaker endpoint health)
3. Review voice agent container logs in CloudWatch

### Daily Webhook Not Receiving Calls

1. Verify pinless dial-in is configured: `curl -H "Authorization: Bearer $DAILY_API_KEY" https://api.daily.co/v1`
2. Check the phone number matches exactly (including country code)
3. Ensure the webhook URL is HTTPS (API Gateway provides this)
4. See [Daily.co Setup Guide](../docs/reference/daily-setup.md) for troubleshooting

## Cost Estimate

| Component | Cloud API Mode | SageMaker Mode |
|-----------|---------------|----------------|
| ECS Fargate (1 task, 2 vCPU / 4 GB) | ~$70/month | ~$70/month |
| SageMaker STT (ml.g6.2xlarge) | N/A | ~$680/month |
| SageMaker TTS (ml.g6.12xlarge) | N/A | ~$3,400/month |
| Bedrock Claude Haiku | ~$0.25/1M input tokens | ~$0.25/1M input tokens |
| Deepgram Cloud STT | ~$0.0043/min | N/A |
| Cartesia Cloud TTS | ~$0.015/1K chars | N/A |
| Daily.co | ~$0.025/min + $2/month per number | ~$0.025/min + $2/month per number |
| VPC NAT Gateway | ~$65/month (2 AZs) | ~$65/month (2 AZs) |

**Cloud API mode** is significantly cheaper for low-to-moderate call volumes but routes audio through the public internet. **SageMaker mode** has higher fixed costs but keeps all audio within your VPC.
