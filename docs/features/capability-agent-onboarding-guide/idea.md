---
name: Capability Agent Onboarding Guide
type: enhancement
priority: P1
effort: medium
impact: high
status: idea
created: 2026-02-23
related-to: dynamic-capability-registry
---

# Capability Agent Onboarding Guide

## Problem Statement

The voice agent platform supports dynamically discovering and invoking capability agents via the A2A protocol and CloudMap, but there is no developer-facing documentation that explains how to add a new capability agent end-to-end. The architecture is spread across Python application code (`backend/agents/`), CDK infrastructure (`infrastructure/src/`), and discovery logic (`backend/voice-agent/app/a2a/`). A developer wanting to add a new agent must reverse-engineer two existing implementations (KB agent, CRM agent) and piece together the Python, Docker, and CDK requirements themselves.

This means:
- **New team members cannot self-serve** -- adding an agent requires tribal knowledge about the A2A protocol, CloudMap registration, ECS metadata endpoints, and the `CapabilityAgentConstruct`.
- **External contributors are blocked** -- without a guide, extending the platform requires reading ~1,500 lines of infrastructure code.
- **Mistakes are likely** -- missing the health check endpoint, forgetting ECR pull grants, or misconfiguring security groups are easy errors with no checklist to prevent them.

## Proposed Solution

A comprehensive developer guide that covers the full lifecycle of adding a new capability agent, structured as a step-by-step walkthrough with code templates derived from the existing KB and CRM agents.

---

## How A2A Auto-Discovery Works

Before building a new agent, it helps to understand the full discovery and invocation flow.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        AWS CloudMap                              │
│                  HTTP Namespace: {project}-{env}-capabilities   │
│                                                                 │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│   │ knowledge-   │  │     crm      │  │  your-agent  │         │
│   │ base service │  │   service    │  │   service    │         │
│   └──────┬───────┘  └──────┬───────┘  └──────┬───────┘         │
└──────────┼─────────────────┼─────────────────┼─────────────────┘
           │                 │                 │
    ECS auto-registers  ECS auto-registers  ECS auto-registers
    task IP:8000        task IP:8000        task IP:8000
           │                 │                 │
           ▼                 ▼                 ▼
   ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
   │  KB Agent     │ │  CRM Agent    │ │  Your Agent   │
   │  (Fargate)    │ │  (Fargate)    │ │  (Fargate)    │
   │               │ │               │ │               │
   │ GET /.well-   │ │ GET /.well-   │ │ GET /.well-   │
   │ known/agent-  │ │ known/agent-  │ │ known/agent-  │
   │ card.json     │ │ card.json     │ │ card.json     │
   │ POST /        │ │ POST /        │ │ POST /        │
   └───────────────┘ └───────────────┘ └───────────────┘
           ▲                 ▲                 ▲
           │                 │                 │
           └─────────────────┼─────────────────┘
                             │
                    A2A invocations
                             │
                    ┌────────┴────────┐
                    │   Voice Agent   │
                    │   (Pipecat)     │
                    │                 │
                    │ AgentRegistry   │
                    │  polls CloudMap │
                    │  every 30s      │
                    └─────────────────┘
```

### Discovery Flow (Automatic -- No Code Changes Required)

1. **CDK deploys your agent** as an ECS Fargate service with a CloudMap service registration.
2. **ECS auto-registers** the running task as a CloudMap instance with attributes `AWS_INSTANCE_IPV4` and `AWS_INSTANCE_PORT`.
3. **Voice agent's `AgentRegistry`** polls CloudMap every 30 seconds (`discovery.py`), calling `servicediscovery:DiscoverInstances` with `HealthStatus="HEALTHY"`.
4. **For each new endpoint**, the registry fetches `GET {url}/.well-known/agent-card.json` via `A2AAgent.get_agent_card()` (`registry.py:200`).
5. **Skills from the Agent Card** (auto-generated from your `@tool` docstrings) are extracted and mapped to Bedrock tool specs with a single `query: str` parameter (`registry.py:355-388`).
6. **Atomic table swap** -- the new skill-to-agent routing table replaces the old one so readers never see a partial state.

### Invocation Flow (During a Call)

1. **Pipeline setup** (`pipeline_ecs.py:631`) calls `registry.get_tool_definitions()` and registers each A2A skill as a Pipecat tool handler via `create_a2a_tool_handler()`.
2. **LLM decides** to call your tool based on the tool name and description (from your `@tool` docstring).
3. **Pipecat routes** to the A2A tool handler (`tool_adapter.py`), which calls `A2AAgent.invoke_async(query)`.
4. **Your agent receives** the request at `POST /`, processes it, and returns an A2A response.
5. **Response text** is extracted and fed back to the LLM for speech synthesis.

Key design decisions:
- **Local tools take precedence**: if a local tool name conflicts with an A2A skill ID, the local tool wins and the A2A skill is skipped (logged as "shadowed").
- **Single `query` parameter**: all A2A tool specs use `query: str` because Agent Card skills don't include input schemas. The remote agent handles parameter extraction.
- **Caching**: successful A2A responses are cached per tool handler (TTL configurable via `A2A_CACHE_TTL_SECONDS`, default 60s).

---

## Step-by-Step: Adding a New Capability Agent

### Prerequisites

- The voice agent ECS stack is deployed (Phase 6) -- it creates the CloudMap namespace
- `enable-capability-registry` SSM flag is set to `true` at `/voice-agent/config/enable-capability-registry`
- Python 3.12+, Docker, and CDK are available locally

### Step 1: Create the Agent Directory

```bash
mkdir -p backend/agents/my-agent/
```

Your agent needs three files:

```
backend/agents/my-agent/
├── main.py           # Agent application
├── requirements.txt  # Python dependencies
└── Dockerfile        # Container image
```

### Step 2: Write the Agent Application (`main.py`)

The minimal structure follows this pattern (derived from `backend/agents/knowledge-base-agent/main.py` and `backend/agents/crm-agent/main.py`):

```python
#!/usr/bin/env python3
"""My Capability Agent.

A standalone A2A-compliant agent that provides [describe capability]
via the A2A protocol. Deployed as an independent ECS Fargate service,
discovered by the voice agent via CloudMap.

Environment variables:
    MY_CONFIG_VAR: Description (required/optional)
    AWS_REGION: AWS region (default: us-east-1)
    LLM_MODEL_ID: Bedrock model for Strands Agent
    PORT: Server port (default: 8000)
    AGENT_NAME: Agent name for logging
"""

import logging
import os
import time

import requests
from strands import Agent, tool
from strands.models import BedrockModel
from strands.multiagent.a2a import A2AServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("my-agent")

# Configuration from environment
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
LLM_MODEL_ID = os.getenv(
    "LLM_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
)
PORT = int(os.getenv("PORT", "8000"))


def _get_task_private_ip() -> str | None:
    """Get this ECS task's private IPv4 address from the metadata endpoint.

    In ECS Fargate, the metadata endpoint provides task network info.
    We use this so the Agent Card advertises a reachable URL instead of 0.0.0.0.
    """
    metadata_uri = os.getenv("ECS_CONTAINER_METADATA_URI_V4")
    if not metadata_uri:
        return None
    try:
        resp = requests.get(f"{metadata_uri}/task", timeout=2)
        resp.raise_for_status()
        task_meta = resp.json()
        containers = task_meta.get("Containers", [])
        for container in containers:
            networks = container.get("Networks", [])
            for network in networks:
                addrs = network.get("IPv4Addresses", [])
                if addrs:
                    return addrs[0]
    except Exception as e:
        logger.warning("Failed to get task IP from metadata: %s", e)
    return None


# ─── Define your tools ───────────────────────────────────────────
# Each @tool function becomes a skill in the Agent Card.
# The docstring is critical -- the voice agent's LLM reads it to
# decide when to call this tool.

@tool
def my_tool(query: str) -> dict:
    """[Write a clear, specific description of what this tool does and
    WHEN the LLM should use it. This docstring becomes the tool
    description in the Agent Card and directly affects tool selection
    accuracy.]

    Args:
        query: Natural language query describing what to look up/do.

    Returns:
        Dictionary with results.
    """
    logger.info("Processing query: %s", query[:100])
    start = time.monotonic()

    # ... your implementation here ...
    result = {"status": "ok", "data": "..."}

    elapsed_ms = (time.monotonic() - start) * 1000
    logger.info("Tool completed: %.1fms", elapsed_ms)
    return result


# ─── Agent setup and server ──────────────────────────────────────

def main():
    """Start the A2A agent server."""
    model = BedrockModel(
        model_id=LLM_MODEL_ID,
        region_name=AWS_REGION,
    )

    agent = Agent(
        name="My Agent",
        description=(
            "Brief description of the agent's overall purpose. "
            "This appears in the Agent Card but is NOT used for "
            "tool selection -- only @tool docstrings matter."
        ),
        model=model,
        tools=[my_tool],  # List all @tool functions here
        callback_handler=None,
    )

    task_ip = _get_task_private_ip()
    http_url = f"http://{task_ip}:{PORT}/" if task_ip else None

    server = A2AServer(
        agent=agent,
        host="0.0.0.0",
        port=PORT,
        http_url=http_url,
        version="0.1.0",
    )

    logger.info("Starting My Agent on port %d", PORT)
    logger.info("Agent Card URL: %s", http_url or f"http://0.0.0.0:{PORT}/")
    server.serve()


if __name__ == "__main__":
    main()
```

#### Key Requirements for `main.py`

| Requirement | Why | Reference |
|---|---|---|
| Use `@tool` decorator from `strands` | Auto-generates Agent Card skills with proper descriptions | `backend/agents/knowledge-base-agent/main.py:111` |
| Write detailed `@tool` docstrings | The voice agent's LLM uses these to decide when to call your tool | `backend/voice-agent/app/a2a/registry.py:355-388` |
| Include `_get_task_private_ip()` | Agent Card must advertise a reachable IP, not `0.0.0.0` | `backend/agents/knowledge-base-agent/main.py:69-97` |
| Return `dict` from tool functions | Results are serialized as JSON in the A2A response | `backend/agents/knowledge-base-agent/main.py:124` |
| Bind to `0.0.0.0` on port 8000 | ECS tasks need to accept connections on all interfaces | `backend/agents/knowledge-base-agent/main.py:375-381` |

#### Single-Tool Optimization (Optional)

If your agent has exactly **one tool** and doesn't need LLM reasoning to route between tools, you can bypass the inner Strands LLM call for ~8x latency reduction (~2.7s to ~323ms). See `backend/agents/knowledge-base-agent/main.py:251-328` for the `DirectToolExecutor` pattern:

```python
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, TaskState, TextPart

class DirectToolExecutor(AgentExecutor):
    def __init__(self, tool_func):
        self._tool_func = tool_func

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.update_status(TaskState.working)
        query = context.get_user_input()
        result = await asyncio.to_thread(self._tool_func, query=query)
        result_text = json.dumps(result, default=str)
        msg = updater.new_agent_message([Part(root=TextPart(text=result_text))])
        await updater.complete(message=msg)

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel()

# After creating the A2AServer:
server.request_handler.agent_executor = DirectToolExecutor(my_tool)
```

Multi-tool agents (like the CRM agent with 5 tools) should **not** use `DirectToolExecutor` -- they need the Strands LLM to reason about which tool to call and synthesize results.

### Step 3: Create `requirements.txt`

```
# Strands SDK with A2A protocol support
strands-agents[a2a]>=1.27.0

# AWS SDK (if your agent calls AWS services)
boto3>=1.34.0

# HTTP client for ECS metadata endpoint (required)
requests>=2.31.0

# Add your agent-specific dependencies here
```

### Step 4: Create the `Dockerfile`

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# curl is required for the health check
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (security best practice)
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Health check hits the Agent Card endpoint
# This is what CloudMap uses to determine instance health
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/.well-known/agent-card.json || exit 1

CMD ["python", "main.py"]
```

**Critical**: The `HEALTHCHECK` must target `/.well-known/agent-card.json` because the Strands `A2AServer` does not expose a `/health` route. This endpoint validates that the A2A protocol layer is fully initialized.

### Step 5: Create the CDK Stack

Create `infrastructure/src/stacks/my-agent-stack.ts`:

```typescript
import * as cdk from 'aws-cdk-lib';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as servicediscovery from 'aws-cdk-lib/aws-servicediscovery';
import * as path from 'path';
import { Construct } from 'constructs';
import { VoiceAgentConfig } from '../config';
import { SSM_PARAMS } from '../ssm-parameters';
import { CapabilityAgentConstruct } from '../constructs';

export interface MyAgentStackProps extends cdk.StackProps {
  readonly config: VoiceAgentConfig;
}

export class MyAgentStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: MyAgentStackProps) {
    super(scope, id, props);

    const { config } = props;
    const resourcePrefix = `${config.projectName}-${config.environment}`;

    // ── Import cross-stack dependencies from SSM ──────────────
    // VPC uses valueFromLookup (synth-time) for Vpc.fromLookup()
    const vpcId = ssm.StringParameter.valueFromLookup(
      this, SSM_PARAMS.VPC_ID
    );
    // Everything else uses valueForStringParameter (deploy-time)
    const voiceAgentSgId = ssm.StringParameter.valueForStringParameter(
      this, SSM_PARAMS.ECS_TASK_SG_ID
    );
    const namespaceId = ssm.StringParameter.valueForStringParameter(
      this, SSM_PARAMS.A2A_NAMESPACE_ID
    );
    const namespaceName = ssm.StringParameter.valueForStringParameter(
      this, SSM_PARAMS.A2A_NAMESPACE_NAME
    );
    const ecsClusterArn = ssm.StringParameter.valueForStringParameter(
      this, SSM_PARAMS.ECS_CLUSTER_ARN
    );

    // ── Import resources ──────────────────────────────────────
    const vpc = ec2.Vpc.fromLookup(this, 'ImportedVpc', { vpcId });

    const voiceAgentSg = ec2.SecurityGroup.fromSecurityGroupId(
      this, 'VoiceAgentSG', voiceAgentSgId
    );

    const namespace = servicediscovery.HttpNamespace
      .fromHttpNamespaceAttributes(this, 'ImportedNamespace', {
        namespaceId,
        namespaceName,
        namespaceArn: `arn:aws:servicediscovery:${this.region}:${this.account}:namespace/${namespaceId}`,
      });

    const cluster = ecs.Cluster.fromClusterAttributes(
      this, 'ImportedCluster', {
        clusterName: `${resourcePrefix}-voice-agent`,
        clusterArn: ecsClusterArn,
        vpc,
        securityGroups: [],
      }
    );

    // ── Build Docker image ────────────────────────────────────
    const containerImage = new ecr_assets.DockerImageAsset(
      this, 'MyAgentImage', {
        directory: path.join(
          __dirname, '..', '..', '..', 'backend', 'agents', 'my-agent'
        ),
        platform: ecr_assets.Platform.LINUX_AMD64,
      }
    );

    // ── Deploy with CapabilityAgentConstruct ──────────────────
    const myAgent = new CapabilityAgentConstruct(this, 'MyAgent', {
      agentName: 'my-agent',           // CloudMap service name
      environment: config.environment,
      projectName: config.projectName,
      cluster,
      vpc,
      namespace,
      voiceAgentSecurityGroup: voiceAgentSg,
      containerImage: ecs.ContainerImage.fromDockerImageAsset(containerImage),
      cpu: 256,                        // 0.25 vCPU (sufficient for most agents)
      memoryLimitMiB: 512,             // 512 MB
      containerPort: 8000,
      enableBedrockAccess: true,       // Set false if agent doesn't call Bedrock
      environment_vars: {
        // Agent-specific config
        MY_CONFIG_VAR: 'value',
      },
      additionalPolicies: [
        // Add IAM policies for any AWS services your agent calls
        // Example: DynamoDB access
        // new iam.PolicyStatement({
        //   actions: ['dynamodb:GetItem', 'dynamodb:Query'],
        //   resources: ['arn:aws:dynamodb:...'],
        // }),
      ],
    });

    // Grant ECR pull to the execution role
    containerImage.repository.grantPull(
      myAgent.taskDefinition.executionRole!
    );
  }
}
```

#### What `CapabilityAgentConstruct` Creates for You

The construct (`infrastructure/src/constructs/capability-agent-construct.ts`) handles:

| Resource | Details |
|---|---|
| **Security group** | Allows inbound TCP 8000 from voice agent SG only |
| **CloudWatch log group** | `/ecs/{prefix}-{agentName}-agent`, 2-week retention |
| **IAM task role** | Bedrock model invocation (if enabled) + your additional policies |
| **IAM execution role** | ECR pull + CloudWatch Logs |
| **Fargate task definition** | X86_64 Linux, configurable CPU/memory |
| **CloudMap service** | Registered in the shared HTTP namespace |
| **ECS Fargate service** | Private subnets, circuit breaker with rollback, no public IP |
| **CloudMap association** | ECS auto-registers/deregisters task instances |

### Step 6: Register the Stack

**6a.** Export from `infrastructure/src/stacks/index.ts`:

```typescript
export { MyAgentStack, MyAgentStackProps } from './my-agent-stack';
```

**6b.** Import and instantiate in `infrastructure/src/main.ts`:

```typescript
import { MyAgentStack } from './stacks';

// Phase 11: My Agent Stack
const myAgentStack = new MyAgentStack(app, 'VoiceAgentMyAgent', {
  env,
  config,
  description: 'Voice Agent POC - My Capability Agent',
  tags: {
    Project: config.projectName,
    Environment: config.environment,
    Phase: '11',
  },
});
myAgentStack.addDependency(ecsStack);  // Always depends on ECS stack
// Add other dependencies as needed:
// myAgentStack.addDependency(someBackendStack);
```

### Step 7: Deploy

```bash
# Ensure the capability registry feature flag is enabled
aws ssm put-parameter \
  --name "/voice-agent/config/enable-capability-registry" \
  --value "true" \
  --type String \
  --overwrite \
  --profile voice-agent

# Deploy your agent stack
npx cdk deploy VoiceAgentMyAgent --profile voice-agent
```

### Step 8: Verify

After deployment, the voice agent will automatically discover your agent within 30 seconds (the default polling interval). Check the voice agent logs for:

```
agent_registry_agent_discovered  agent_name=My Agent  url=http://10.0.x.x:8000/  skills=['my_tool']
agent_registry_skills_added  skills=['my_tool']
```

You can also verify the Agent Card directly:

```bash
# From within the VPC (e.g., via ECS exec into the voice agent container)
curl http://<agent-task-ip>:8000/.well-known/agent-card.json | jq .
```

---

## Compatibility Checklist

Before deploying, verify your agent meets all requirements:

- [ ] **Port 8000**: Agent listens on port 8000 (or matches `containerPort` in CDK)
- [ ] **`/.well-known/agent-card.json`**: Responds to GET requests (automatic with `A2AServer`)
- [ ] **`POST /`**: Accepts A2A task requests (automatic with `A2AServer`)
- [ ] **`_get_task_private_ip()`**: Agent Card advertises the ECS task's private IP, not `0.0.0.0`
- [ ] **`@tool` docstrings**: Every tool has a clear, detailed docstring (the LLM reads these)
- [ ] **Tool names are unique**: No collision with existing tool names (`search_knowledge_base`, `lookup_customer`, `create_support_case`, `add_case_note`, `verify_account_number`, `verify_recent_transaction`, `transfer_call`, `get_current_time`)
- [ ] **Tools return `dict`**: JSON-serializable return values
- [ ] **Dockerfile health check**: `curl -f http://localhost:8000/.well-known/agent-card.json`
- [ ] **Dockerfile includes `curl`**: Required for the health check
- [ ] **Non-root user**: Container runs as `appuser` (security)
- [ ] **`requests` in requirements**: Required for `_get_task_private_ip()` (ECS metadata endpoint)
- [ ] **`strands-agents[a2a]>=1.27.0`**: The `[a2a]` extra is required for `A2AServer`
- [ ] **CDK grants ECR pull**: `containerImage.repository.grantPull(agent.taskDefinition.executionRole!)`
- [ ] **CDK stack depends on `ecsStack`**: The CloudMap namespace and ECS cluster must exist first

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Agent not discovered | Feature flag disabled | Set `/voice-agent/config/enable-capability-registry` to `true` in SSM |
| Agent not discovered | Health check failing | Check container logs; ensure `curl` is installed and port 8000 is serving |
| Agent Card fetch fails | Wrong IP in Agent Card | Verify `_get_task_private_ip()` is implemented and `ECS_CONTAINER_METADATA_URI_V4` is available |
| Tool not appearing | Skill name conflicts with local tool | Rename your `@tool` function -- local tools shadow A2A tools with the same name |
| Tool calls timeout | Agent takes >30s to respond | Increase `A2A_CACHE_TTL_SECONDS` or optimize your tool; check `/voice-agent/a2a/tool-timeout-seconds` SSM param |
| "Connection refused" | Security group misconfigured | Verify `CapabilityAgentConstruct` has the correct `voiceAgentSecurityGroup` reference |
| Multiple agents, same skill | Duplicate skill IDs across agents | Use unique function names for `@tool` decorators; duplicates are logged as warnings |

## Affected Areas

- `backend/agents/` -- New agent directory
- `infrastructure/src/stacks/` -- New CDK stack
- `infrastructure/src/stacks/index.ts` -- Export new stack
- `infrastructure/src/main.ts` -- Instantiate and wire dependencies

## Success Criteria

- [ ] Developer can add a new capability agent by following this guide without reading any other source code
- [ ] Guide covers all three layers: Python application, Docker container, CDK infrastructure
- [ ] Compatibility checklist prevents common deployment failures
- [ ] Troubleshooting table covers the most frequent issues

## Dependencies

- `dynamic-capability-registry` (shipped) -- The A2A discovery system this guide documents
- `strands-agents[a2a]>=1.27.0` -- Strands SDK with A2A support
- AWS CloudMap HTTP namespace (created by ECS stack, Phase 6)
