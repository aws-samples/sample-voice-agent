---
id: capability-agent-onboarding-guide
name: Capability Agent Onboarding Guide
type: enhancement
priority: P1
effort: Medium
impact: High
created: 2026-02-23
started: 2026-02-23
shipped: 2026-02-23
---

# Capability Agent Onboarding Guide - Shipped

## Summary

Created a comprehensive, self-service developer guide that enables any engineer to build, deploy, and validate a new A2A capability agent without tribal knowledge or reverse-engineering existing implementations. Consolidated information previously spread across the idea.md, pattern doc, and AGENTS.md into a single authoritative walkthrough. Also created an OpenCode skill for scaffolding new agents and added cross-references across all relevant project documentation.

## What Was Built

### Primary Developer Guide (`docs/guides/adding-a-capability-agent.md`)
- 8-step walkthrough: directory structure, Python agent, requirements, Dockerfile, CDK stack, registration, deploy, verify
- Mermaid sequence diagram showing the auto-discovery lifecycle
- Mermaid flowchart for execution pattern decision (DirectToolExecutor vs StrandsA2AExecutor)
- "Why ECS Fargate?" rationale section with ECS vs Lambda comparison table
- Code templates derived from actual shipped KB and CRM agent implementations
- DirectToolExecutor pattern with full code and wiring instructions
- CDK stack template with SSM import pattern and CapabilityAgentConstruct usage
- 14-item compatibility checklist
- Existing tool names conflict table (8 tools)
- Tool description best practices with good/bad docstring examples
- 8-row troubleshooting table
- Available SSM parameters reference table

### Updated Pattern Doc (`docs/patterns/capability-agent-pattern.md`)
- Replaced all `A2AStarletteApplication` references with `A2AServer` from `strands.multiagent.a2a`
- Replaced all `DefaultRequestHandler` references with current API
- Fixed `DirectToolExecutor` code snippet to match shipped KB agent (async `updater.update_status()`, `updater.new_agent_message()`, typed `RequestContext`)
- Updated Dockerfile template (added curl, appuser, HEALTHCHECK)
- Updated CDK template with full SSM import pattern and `_get_task_private_ip()`
- Added cross-references to new guide

### OpenCode Skill (`.opencode/skills/create-capability-agent/SKILL.md`)
- Loadable via `skill({ name: "create-capability-agent" })`
- Requirements gathering checklist (agent name, tools, execution pattern, AWS services)
- Step-by-step scaffolding instructions for all 5 file types
- Key patterns and compatibility checklist reminder

### Cross-References Added
- `README.md`: new "Developer Guides" section, `docs/guides/` added to project tree
- `ARCHITECTURE.md`: cross-reference in A2A architecture section
- `infrastructure/DEPLOYMENT.md`: cross-reference in Step 9
- `backend/voice-agent/README.md`: cross-reference in Features list
- `AGENTS.md`: cross-references to guide and pattern doc

## Quality Gates

### Security Review: APPROVED
- Zero new security findings across all 9 files reviewed
- No credential exposure, no real infrastructure IDs, scoped IAM templates
- Dockerfile templates follow security best practices (non-root, health checks)
- Pre-existing AWS account ID in AGENTS.md noted for separate tracking

### QA Validation: APPROVED
- 65/65 checks passed across accuracy, completeness, cross-references, and consistency
- All code templates verified against shipped KB/CRM agent implementations
- All 7 SSM parameter paths verified against `ssm-parameters.ts`
- All 15 cross-reference links resolve correctly
- Zero deprecated API references (`A2AStarletteApplication`, `DefaultRequestHandler`) remaining

## Files Changed

```
New:
  docs/guides/adding-a-capability-agent.md                    # Primary developer guide
  .opencode/skills/create-capability-agent/SKILL.md           # OpenCode scaffolding skill

Modified:
  docs/patterns/capability-agent-pattern.md                   # Fix outdated API refs, add cross-refs
  AGENTS.md                                                   # Add cross-references to guide and pattern doc
  README.md                                                   # Add Developer Guides section, update project tree
  ARCHITECTURE.md                                             # Add cross-reference in A2A section
  infrastructure/DEPLOYMENT.md                                # Add cross-reference in Step 9
  backend/voice-agent/README.md                               # Add cross-reference in Features list
```
