---
id: scaling-load-test
name: Auto-Scaling Load Test Harness
type: feature
priority: P1
effort: Large
impact: High
status: shipped
shipped: 2026-02-27
---

# Auto-Scaling Load Test Harness - Shipped

## Summary

Built a comprehensive load testing harness for validating ECS auto-scaling behavior. The tool can place 50+ concurrent SIP calls, exercise scale-out/scale-in policies, and verify task protection prevents dropped calls during scaling events.

## What Was Delivered

### Test Infrastructure (Sibling Repo: asset-scaling-load-test)

**Core Components:**
1. **SIPp Test Runner** - Places concurrent SIP calls via Asterisk to voice agent
2. **Scenario Files** - XML scenarios for various load patterns (steady-state, burst, sustained)
3. **Audio Files** - Pre-recorded PCMU audio for realistic conversation simulation
4. **Metrics Poller** - CloudWatch integration to track scaling behavior
5. **CDK Stack** - Deploys test infrastructure (EC2 instance, S3 bucket, IAM roles)

**Test Scenarios Implemented:**

| Scenario | Description | Validation |
|----------|-------------|------------|
| Steady-State Scale-Out | 4→8 calls, verify scale to 2→4 tasks | Task count increases |
| Burst Scale-Out | 20 simultaneous calls, verify step scaling | Step policy fires |
| Scale-In Protection | End calls on some tasks, verify protection | Only idle tasks terminated |
| Sustained Load | 50 calls for 10 minutes | Zero dropped calls, latency < 3s |

### Key Features

- **Configurable Thresholds**: Lowered `targetSessionsPerTask` for observable scaling
- **Synthetic Audio**: Pre-recorded prompts trigger realistic conversation flows
- **Metrics Integration**: Polls `SessionsPerTask`, `DesiredCount`, `RunningCount`
- **Pass/Fail Assertions**: Validates scaling behavior against expected outcomes
- **Clean SIP Termination**: Sends BYE on timeout to prevent 5-minute delays

### Files Created/Modified

**In asset-scaling-load-test repo:**
- `sipp/uac_asterisk.xml` - Main test scenario with 30s timeout and BYE handling
- `sipp/audio/calls_pcmu/` - Pre-recorded audio files (180s and 600s variants)
- `scripts/ec2_shell.py` - Remote execution on SIPp instance
- `scripts/upload_to_ec2.py` - File deployment via S3 + SSM
- `infrastructure/cdk/src/constructs/sipp-instance.ts` - EC2 instance with SIPp

### Recent Improvements

- Updated SIPp scenario to send BYE after 30s timeout (prevents 5-minute hangup delays)
- Changed default audio from 600s to 180s for faster test cycles
- Added clear documentation on clean hangup propagation

## Validation Results

**Test Call Performance:**
- Call completion time: ~30 seconds (with BYE timeout)
- Participant join to leave: ~24 seconds
- Time from participant_leave to session_end: 1-2 seconds
- Zero `InvalidStateError` tracebacks (BiDi teardown fix applied)

**Scaling Behavior Verified:**
- ECS scales out when sessions exceed target per task
- ECS scales in after calls end (with cooldown)
- Task protection prevents termination of active call handlers
- CloudWatch metrics accurately reflect session distribution

## Usage

```bash
# Run single test call
AWS_PROFILE=voice-agent uv run python scripts/ec2_shell.py \
  "sipp 10.0.0.159:5060 -sf /opt/sipp/scenarios/uac_asterisk.xml \
   -l 1 -m 1 -r 1 -rp 1000 -i <local_ip> -mp 6000 \
   -rtp_payload 0 -trace_err -timeout 35"

# Upload updated scenarios
AWS_PROFILE=voice-agent uv run python scripts/upload_to_ec2.py \
  sipp/uac_asterisk.xml /opt/sipp/scenarios/
```

## Impact

- **Confidence**: Validates auto-scaling works before production deployment
- **Regression Testing**: Re-run after infrastructure changes
- **Cost Optimization**: Test with lowered thresholds to observe behavior
- **Reliability**: Verifies task protection prevents dropped calls

## Related Features

- [ecs-auto-scaling](./ecs-auto-scaling/) - The scaling behavior being tested
- [comprehensive-observability-metrics](./comprehensive-observability-metrics/) - CloudWatch metrics integration
- [sip-testing-environment](./sip-testing-environment/) - SIP test infrastructure foundation
