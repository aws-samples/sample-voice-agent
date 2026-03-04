---
name: create-capability-agent
description: Scaffold a new A2A capability agent with Python application, Dockerfile, requirements.txt, and CDK stack following the project's established patterns
---

## What I Do

Scaffold all the files needed for a new A2A capability agent in the voice agent platform. This includes:

1. Python agent application (`backend/agents/{name}/main.py`)
2. Dependencies (`backend/agents/{name}/requirements.txt`)
3. Container image (`backend/agents/{name}/Dockerfile`)
4. CDK infrastructure stack (`infrastructure/src/stacks/{name}-agent-stack.ts`)
5. Stack registration (exports in `index.ts`, instantiation in `main.ts`)

## When to Use Me

Use this skill when you need to create a new capability agent that will be discovered via CloudMap and invoked over the A2A protocol by the voice agent.

## Reference

Read `docs/guides/adding-a-capability-agent.md` for the complete developer guide. All templates below are derived from that guide and the shipped KB and CRM agent implementations.

## Steps

### 1. Gather Requirements

Ask the user for:
- **Agent name** (kebab-case, e.g., `inventory-agent`). This becomes the directory name and CloudMap service name.
- **Tool descriptions** -- what tools should the agent expose? For each tool, get:
  - Function name (snake_case, must be unique -- check existing names in the guide)
  - What it does (this becomes the `@tool` docstring, which is critical for LLM tool selection)
  - Parameters and return type
- **Execution pattern** -- single tool (DirectToolExecutor, ~300ms) or multi-tool (StrandsA2AExecutor, ~2-3s)?
- **AWS services needed** -- does it call Bedrock, DynamoDB, S3, or external APIs? This determines IAM policies and env vars.
- **Backend dependencies** -- does it depend on other CDK stacks (e.g., a database stack)?

### 2. Create the Agent Directory

```bash
mkdir -p backend/agents/{name}/tests/
```

### 3. Create main.py

Follow the template in `docs/guides/adding-a-capability-agent.md` (Step 2). Key requirements:

- Use `from strands.multiagent.a2a import A2AServer` (NOT `A2AStarletteApplication`)
- Use `from strands.models import BedrockModel` (NOT `from strands.models.bedrock`)
- Include `_get_task_private_ip()` function (required boilerplate for Agent Card URL)
- Write detailed `@tool` docstrings -- the voice agent's LLM uses these for tool selection
- All tools must return `dict` (JSON-serializable)
- For single-tool agents, include `DirectToolExecutor` and swap it after creating the server:
  ```python
  server.request_handler.agent_executor = DirectToolExecutor(my_tool)
  ```
- Add warm-up in `main()`: pre-initialize boto3 clients and optionally probe the Strands agent

### 4. Create requirements.txt

Base dependencies (always required):
```
strands-agents[a2a]>=1.27.0
requests>=2.31.0
```

Add `boto3>=1.34.0` if calling AWS services. Add `cachetools>=5.3.0` if implementing result caching.

Also create `requirements-test.txt` for test dependencies:
```
-r requirements.txt
pytest>=8.0.0
pytest-asyncio>=0.23.0  # if using DirectToolExecutor or async tests
requests-mock>=1.11.0   # if the agent makes HTTP calls
```

### 5. Create Dockerfile

Use the exact template from `docs/guides/adding-a-capability-agent.md` (Step 4). Critical requirements:
- Base image: `python:3.12-slim`
- Install `curl` (required for health check)
- Create `appuser` (non-root)
- HEALTHCHECK must target `/.well-known/agent-card.json` (NOT `/health`)
- CMD: `["python", "main.py"]`

### 6. Create CDK Stack

Create `infrastructure/src/stacks/{name}-agent-stack.ts` following the template in `docs/guides/adding-a-capability-agent.md` (Step 5). Key patterns:
- Import `VoiceAgentConfig` from `../config`
- Import `SSM_PARAMS` from `../ssm-parameters`
- Import `CapabilityAgentConstruct` from `../constructs`
- VPC: `ssm.StringParameter.valueFromLookup` (synth-time)
- All other SSM params: `ssm.StringParameter.valueForStringParameter` (deploy-time)
- Use `ecr_assets.DockerImageAsset` with `Platform.LINUX_AMD64`
- Use `CapabilityAgentConstruct` with agent-specific config
- Grant ECR pull: `containerImage.repository.grantPull(agent.taskDefinition.executionRole!)`

### 7. Register the Stack

Add export to `infrastructure/src/stacks/index.ts`:
```typescript
export { MyAgentStack, MyAgentStackProps } from './{name}-agent-stack';
```

Add instantiation to `infrastructure/src/main.ts`:
```typescript
const myAgentStack = new MyAgentStack(app, 'VoiceAgentMyAgent', {
  env, config,
  description: 'Voice Agent POC - My Capability Agent',
  tags: { Project: config.projectName, Environment: config.environment, Phase: '<next>' },
});
myAgentStack.addDependency(ecsStack);
```

Current phases: KB agent = Phase 9, CRM agent = Phase 10. Use the next available phase number.

### 8. Write Tests

Create `backend/agents/{name}/tests/__init__.py` (empty) and `backend/agents/{name}/tests/test_{name}.py`.

Follow the patterns established by the existing agent tests:
- `backend/agents/crm-agent/tests/test_crm_client.py` -- CRM client HTTP interactions (uses `requests-mock`)
- `backend/agents/crm-agent/tests/test_tools.py` -- Tool functions with mocked client
- `backend/agents/knowledge-base-agent/tests/test_knowledge_base.py` -- KB search tool + DirectToolExecutor (uses `pytest-asyncio`)

Key patterns:
- Patch env vars before importing `main.py` (it reads env vars at module level)
- Mock external service clients (boto3, HTTP) -- never call real services in unit tests
- Test input validation (empty/whitespace, invalid values)
- Test error handling (service errors, network errors, unconfigured state)
- Test happy path with mocked responses
- For `DirectToolExecutor` tests, use `@pytest.mark.asyncio`

Run tests:
```bash
cd backend/agents/{name} && pip install -r requirements-test.txt && pytest tests/ -v
```

### 9. Run the Compatibility Checklist

Before finishing, verify all items from the checklist in `docs/guides/adding-a-capability-agent.md`:
- Port 8000, Agent Card endpoint, `_get_task_private_ip()`, unique tool names, dict returns, Dockerfile health check, curl installed, non-root user, `requests` in requirements, `strands-agents[a2a]>=1.27.0`, ECR pull grant, ecsStack dependency.
