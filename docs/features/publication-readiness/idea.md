---
name: Publication Readiness
type: tech-debt
priority: P0
effort: large
impact: high
status: idea
created: 2026-03-01
related-to: []
depends-on: []
---

# Publication Readiness

## Problem Statement

This project needs to be prepared for public publication as an AWS Sample. The codebase currently contains hardcoded AWS account IDs, internal tooling references (ada, Isengard, internal GitLab), live infrastructure identifiers, and internal developer notes that must be removed or replaced before the repository can be made public. Additionally, standard open-source files (LICENSE, CONTRIBUTING.md) are missing, deployment documentation needs to be self-contained for external users, and OpenCode skills should be created to assist with the deployment process.

## Audit Findings

### Critical: Sensitive Information in Committed Files

**Hardcoded AWS Account IDs** -- Two account IDs appear across 30+ locations in committed files:

| File | Issue |
|------|-------|
| `AGENTS.md` | Account ID and `ada profile add` command |
| `infrastructure/outputs-VoiceAgentEcs.json` | Full ARNs, ECR URIs, bucket names |
| `infrastructure/outputs-VoiceAgentBotRunner.json` | Full ARNs, ECR URIs |
| `infrastructure/outputs.json` | Secret ARN, ECR URI |
| `infrastructure/outputs-VoiceAgentAgentCore.json` | ECR URIs, AgentCore ARN, IAM role |
| `infrastructure/cdk.context.json` | Full VPC topology, subnet IDs, security groups, KMS key ARNs |
| `infrastructure/.env` | `AWS_ACCOUNT_ID` value |
| `docs/features/*/shipped.md`, `*/idea.md`, `*/plan.md` | Account IDs, API Gateway URLs, private offer IDs |
| `docs/features/observability-foundation/shipped.md` | "Deployed to ECS in account ..." |
| `docs/features/cdk-resource-naming-cleanup/idea.md` | Full ECS cluster ARN |

**Live Infrastructure Identifiers** in committed output files:

- VPC IDs, Subnet IDs, Security Group IDs
- KMS Key ARNs, Secrets Manager ARNs
- API Gateway URLs, ELB hostnames
- Lambda function ARNs, DynamoDB table ARNs
- Knowledge Base IDs, CloudMap namespace IDs
- SIP server public IPs
- Deepgram private offer IDs (4 occurrences)

### High: Internal Tooling References

| Reference | Files Affected |
|-----------|---------------|
| `ada` credential tool | `AGENTS.md`, `.claude/settings.local.json` |
| `--profile voice-agent` | 25+ locations across docs, tests, scripts, skills |
| `git@ssh.gitlab.aws.dev:...` | Git remote origin |
| `isengard` provider | `AGENTS.md` |
| Internal Claude Code plugins (`epcc-workflow@aws-claude-code-plugins`, `feature-workflow@schuettc-claude-code-plugins`) | `.claude/settings.json` |
| Developer-local paths (`/Users/schuettc/.toolbox/bin/finch`) | `.claude/settings.local.json` |

### High: Missing Standard Open-Source Files

| File | Status |
|------|--------|
| `LICENSE` | Missing -- README says "Proprietary - AWS Samples" (contradictory) |
| `CONTRIBUTING.md` | Missing |
| `CODE_OF_CONDUCT.md` | Missing |
| `NOTICE` | Missing -- third-party attributions needed for Pipecat, Deepgram, Cartesia, Daily, etc. |

### Medium: Documentation Gaps

- `AGENTS.md` contains internal AWS configuration section not suitable for public readers
- Deployment docs reference `--profile voice-agent` which external users won't have
- No OpenCode skill for guided deployment
- Feature docs contain internal deployment specifics

## Proposed Work

### Phase 1: Secrets and Sensitive Data Removal

1. **Delete infrastructure output files** (committed but contain live resource IDs):
   - `infrastructure/outputs-VoiceAgentEcs.json`
   - `infrastructure/outputs-VoiceAgentBotRunner.json`
   - `infrastructure/outputs.json`
   - `infrastructure/outputs-agentcore-cfn.json`
   - `infrastructure/outputs-agentcore-rebuild.json`
   - `infrastructure/outputs-VoiceAgentAgentCore.json`

2. **Remove tracked context file**:
   - `infrastructure/cdk.context.json` (should be gitignored, is currently tracked)

3. **Sanitize AGENTS.md**:
   - Remove AWS Configuration section (account ID, `ada` command, profile references)
   - Replace with generic instructions ("configure AWS credentials for your target account")

4. **Sanitize infrastructure/.env**:
   - Replace account ID with placeholder `123456789012`
   - Add `.env.example` with placeholder values

5. **Sanitize feature docs** (batch find-and-replace across `docs/features/`):
   - Replace account IDs with `123456789012`
   - Replace API Gateway URLs with `https://<api-id>.execute-api.<region>.amazonaws.com`
   - Replace VPC/subnet/SG IDs with `vpc-EXAMPLE`, `subnet-EXAMPLE`, `sg-EXAMPLE`
   - Replace `--profile voice-agent` with `--profile <your-profile>`
   - Replace Deepgram private offer IDs with `<your-offer-id>`

6. **Clean `.claude/settings.json`**:
   - Remove internal plugin references

### Phase 2: Standard Open-Source Files

7. **Add LICENSE** (MIT-0 for AWS Samples)
8. **Add CONTRIBUTING.md** (standard AWS Samples template)
9. **Add CODE_OF_CONDUCT.md**
10. **Add NOTICE** (third-party attributions: Pipecat, Deepgram, Cartesia, Daily.co, structlog, etc.)
11. **Update README.md** license section from "Proprietary" to actual license

### Phase 3: Documentation for External Users

12. **Rewrite AGENTS.md** for public audience:
    - Generic AWS credential setup instructions
    - Remove all internal references
    - Keep environment variable documentation (already good)

13. **Audit deployment docs** (`infrastructure/DEPLOYMENT.md`):
    - Ensure all prerequisites are listed for a fresh AWS account
    - Replace profile-specific commands with generic alternatives
    - Add troubleshooting section for common first-time issues

14. **Sanitize test files**:
    - `backend/voice-agent/tests/test_bedrock_integration.py` -- remove `voice-agent` profile

15. **Sanitize scripts**:
    - `infrastructure/scripts/setup-daily.sh` -- generic profile handling
    - `infrastructure/scripts/update-daily-webhook.sh` -- generic profile handling

### Phase 4: OpenCode Skills for Deployment

16. **Create `deploy-voice-agent` skill**:
    - Guided walkthrough for first-time deployment
    - Prerequisites check (Node.js, AWS CLI, Docker/finch, SageMaker quotas)
    - Step-by-step CDK bootstrap, secret setup, and stack deployment
    - Post-deploy validation

17. **Update `run-scaling-test` skill**:
    - Remove hardcoded `voice-agent` profile and cluster name
    - Parameterize for any deployment

### Phase 5: Git History Consideration

18. **Evaluate git history scrubbing**:
    - Account IDs exist in commit history even after file deletion
    - Options: (a) BFG Repo Cleaner, (b) fresh initial commit, (c) accept risk since infra can be rotated
    - Recommend fresh initial commit for cleanest publication

## Files to Modify

### Delete
- `infrastructure/outputs-VoiceAgentEcs.json`
- `infrastructure/outputs-VoiceAgentBotRunner.json`
- `infrastructure/outputs.json`
- `infrastructure/outputs-agentcore-cfn.json`
- `infrastructure/outputs-agentcore-rebuild.json`
- `infrastructure/outputs-VoiceAgentAgentCore.json`
- `infrastructure/cdk.context.json`

### Sanitize
- `AGENTS.md`
- `infrastructure/.env`
- `.claude/settings.json`
- `.opencode/skills/run-scaling-test/SKILL.md`
- `backend/voice-agent/tests/test_bedrock_integration.py`
- `infrastructure/scripts/setup-daily.sh`
- `infrastructure/scripts/update-daily-webhook.sh`
- `docs/guides/adding-a-capability-agent.md`
- 40+ files under `docs/features/*/`

### Create
- `LICENSE`
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `NOTICE`
- `infrastructure/.env.example`
- `.opencode/skills/deploy-voice-agent/SKILL.md`

### Update
- `README.md` (license section)
- `infrastructure/DEPLOYMENT.md` (generic profile instructions)

## Acceptance Criteria

- [ ] No AWS account IDs in any committed file (grep for `972801262139` and `046264621987` returns zero results)
- [ ] No `ada` or `isengard` references in any committed file
- [ ] No `--profile voice-agent` in any committed file (replaced with `--profile <your-profile>`)
- [ ] No live VPC/subnet/SG/KMS/API Gateway IDs in committed files
- [ ] No Deepgram private offer IDs in committed files
- [ ] `LICENSE` file present with MIT-0 or Apache-2.0
- [ ] `CONTRIBUTING.md` and `CODE_OF_CONDUCT.md` present
- [ ] `NOTICE` file lists all third-party dependencies and their licenses
- [ ] `README.md` license section matches actual LICENSE file
- [ ] `.env.example` provides placeholder values for all required environment variables
- [ ] Deployment docs work for a user with no internal Amazon access
- [ ] `deploy-voice-agent` OpenCode skill provides guided deployment
- [ ] `run-scaling-test` skill has no hardcoded internal references
- [ ] `.claude/settings.json` has no internal plugin references
- [ ] `cdk.context.json` is properly gitignored and not tracked
- [ ] All tests pass after sanitization

## Estimated Effort

Large: 2-3 days. The bulk of the work is systematic find-and-replace across 50+ files, plus creating the LICENSE/CONTRIBUTING/NOTICE files and the deployment skill. The git history decision may add time if a fresh commit approach is chosen.
