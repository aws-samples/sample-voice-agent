---
name: run-scaling-test
description: Run an ECS scaling validation test with parallel monitoring, baseline enforcement, and automated result documentation
---

## What I Do

Execute an ECS scaling validation scenario from the SIPp load test harness (`../asset-scaling-load-test`) with:

1. Baseline enforcement (1 task, 0 active calls, SIPp healthy)
2. Parallel real-time monitoring (CloudWatch metrics + NLB distribution)
3. Scenario execution with pass/fail assertions
4. Structured results documentation in `docs/results/scaling-tests/`

## When to Use Me

Use this skill when you want to run a scaling validation test against the deployed voice agent stack. Available scenarios:

| Scenario | Duration | What It Tests |
|----------|----------|---------------|
| `steady-state` | ~22 min | Phased scale-out/in with cold start gap |
| `burst` | ~10 min | Heavy-load proportional scale-out |
| `scale-in-protection` | ~15 min | Task protection during scale-in |
| `sustained-24` | ~30 min | Near-max capacity soak test |

## Reference

- Scenarios: `../asset-scaling-load-test/scenarios/*.yaml`
- Load test CLI: `uv run load-test run --scenario <name>` (in `../asset-scaling-load-test`)
- Metrics script: `uv run python scripts/poll_metrics.py --watch` (in `../asset-scaling-load-test`)
- ECS cluster: `voice-agent-poc-poc-voice-agent`
- AWS profile: `voice-agent`
- Results dir: `docs/results/scaling-tests/`

## Steps

### 1. Ask Which Scenario to Run

Ask the user which scenario they want to run. Default recommendation is `steady-state` for first-time validation. Show the table from "When to Use Me" above.

### 2. Validate Baseline

Before starting, verify all preconditions. Run these checks:

```bash
# Check ECS: must be 1 running, 1 desired, 0 pending
aws ecs describe-services \
  --cluster voice-agent-poc-poc-voice-agent \
  --services voice-agent-poc-poc-voice-agent \
  --profile voice-agent --region us-east-1 \
  --query 'services[0].{running:runningCount,desired:desiredCount,pending:pendingCount}'
```

Expected: `{"running": 1, "desired": 1, "pending": 0}`

```bash
# Check SIPp instance is reachable, no running SIPp processes
uv run python scripts/run_sipp.py status
```

Expected: Instance accessible, "No SIPp processes running"

```bash
# Check audio files are present on EC2
uv run python scripts/ec2_shell.py "ls /opt/sipp/audio/calls_pcmu/ | wc -l"
```

Expected: > 0 files

```bash
# One-shot metrics check: sessions should be 0
uv run python scripts/poll_metrics.py
```

Expected: `Active: 0` or no active count

All SIPp/metrics commands run with `workdir` set to `../asset-scaling-load-test`.

**If baseline is NOT met**, attempt recovery:
1. `uv run python scripts/run_sipp.py stop` (kill stale SIPp)
2. Wait 30s, re-check ECS. If tasks > 1, optionally force:
   ```bash
   aws ecs update-service --cluster voice-agent-poc-poc-voice-agent \
     --service voice-agent-poc-poc-voice-agent \
     --desired-count 1 --profile voice-agent --region us-east-1
   ```
3. Poll ECS every 30s until `runningCount == 1`
4. Re-run all baseline checks

### 3. Launch Parallel Monitoring

Before starting the scenario, launch two parallel Task tool sub-agents:

**Agent A -- Metrics Watcher:**
Launch a `general` sub-agent with this prompt:
> Run the following command in workdir `/Users/schuettc/Documents/GitHub/ml-frameworks-voice/asset-scaling-load-test` with a timeout of 5400000ms (90 minutes):
> `uv run python scripts/poll_metrics.py --watch --interval 30`
> Capture all output. When the command is terminated, return the complete output.

**Agent B -- NLB Distribution Checker:**
Launch a `general` sub-agent with this prompt:
> Run the following bash loop in workdir `/Users/schuettc/Documents/GitHub/ml-frameworks-voice/asset-scaling-load-test` with a timeout of 5400000ms:
> ```
> for i in $(seq 1 180); do echo "=== SNAPSHOT $(date -u +%H:%M:%S) ===" ; aws dynamodb scan --table-name $(aws ssm get-parameter --name /voice-agent/dynamodb/session-table-name --profile voice-agent --region us-east-1 --query 'Parameter.Value' --output text) --filter-expression "begins_with(PK, :prefix) AND SK = :sk" --expression-attribute-values '{":prefix":{"S":"TASK#"},":sk":{"S":"HEARTBEAT"}}' --projection-expression "PK, active_session_count" --profile voice-agent --region us-east-1 --output table 2>/dev/null || echo "(no heartbeats)" ; sleep 30 ; done
> ```
> Capture all output. When done, return the complete output showing per-task session distribution over time.

### 4. Execute the Scenario

Run the scenario in the foreground (in `workdir: ../asset-scaling-load-test`):

```bash
uv run load-test run --scenario <SCENARIO_NAME> --config config.yaml
```

Set a generous timeout based on the scenario:
- `steady-state`: 1800000ms (30 min)
- `burst`: 1200000ms (20 min)
- `scale-in-protection`: 1200000ms (20 min)
- `sustained-24`: 3600000ms (60 min)

Capture the full output. The harness prints:
- Step-by-step progress with metrics every 10s
- Assertion results (PASS/FAIL)
- Metrics summary table (last 10 snapshots)
- JSON results file path

### 5. Collect Results

After the scenario completes:

1. Read the JSON results file from `../asset-scaling-load-test/results/<scenario>-*.json` (the most recent one)
2. Collect output from the two monitoring sub-agents
3. Parse key data points:
   - All assertion outcomes (pass/fail)
   - Peak and final task counts
   - Peak MaxSessionsPerTask / SessionsPerTask
   - E2E latency p95
   - Call summary (total, completed, dropped, failed)
   - NLB distribution at peak (from Agent B snapshots)

### 6. Generate Results Document

Create a markdown report at:
```
docs/results/scaling-tests/<scenario>-<YYYY-MM-DD-HHmmss>.md
```

Use this template:

```markdown
# Scaling Test Results: <scenario-name>

**Date**: <YYYY-MM-DD HH:MM UTC>
**Duration**: <M>m <S>s
**Result**: PASSED / FAILED

## Scaling Configuration

| Parameter | Value |
|-----------|-------|
| Target tracking target | 3 (SessionsPerTask avg) |
| Scale-in | -3 per 30s (AvgSessionsPerTask < 1.0) |
| Max capacity | 12 |
| MAX_CONCURRENT_CALLS | 10 |

## Cold Start Timing (Measured)

New tasks take **~90s** from creation to receiving traffic. This is an
irreducible floor driven by the container image size (~824 MB compressed).

| Phase | Duration | Cumulative |
|-------|----------|-----------|
| ENI attach + scheduling | ~14s | 14s |
| Image pull (824 MB) | ~37s | 51s |
| Container init (app start) | ~17s | 68s |
| NLB health check (2 x 10s) | ~20s | **~88s** |

On top of this, the scaling **decision pipeline** adds 1-3 min:

| Phase | Duration |
|-------|----------|
| Session counter Lambda emits metric | every 60s |
| CloudWatch alarm evaluates (1 min period) | 0-60s |
| Target tracking reacts | 0-60s |

**Total: overload detected -> new task serving traffic = ~3-5 min.**

Test scenarios MUST account for this lag. Any calls placed before new
capacity is ready will be rejected (503) by the overloaded task's
`/ready` endpoint. Design scenarios with a wait phase between filling
the first task past the target and sending overflow calls.

## Assertions

| # | Assertion | Expected | Actual | Result |
|---|-----------|----------|--------|--------|
(populate from scenario results)

## Scaling Timeline

| Time | Event | Tasks (R/D) | SessionsPerTask | ActiveCount |
|------|-------|-------------|-----------------|-------------|
(populate from metrics history -- key inflection points)

## NLB Distribution (at peak)

| Task ID | Active Sessions | % of Total |
|---------|----------------|------------|
(populate from Agent B DynamoDB snapshots at peak call count)

## Metrics Summary (last 10 snapshots)

(paste the metrics summary table from the harness output)

## Call Summary

| Metric | Value |
|--------|-------|
| Total calls | N |
| Completed | N |
| Dropped | N |
| Failed | N |
```

### 7. Report to User

Summarize:
- Overall PASS/FAIL
- Number of assertions passed/failed
- Key observations (scaling speed, NLB distribution quality, any anomalies)
- Path to the results document
- Whether baseline is clean for the next test (or if recovery is needed)
