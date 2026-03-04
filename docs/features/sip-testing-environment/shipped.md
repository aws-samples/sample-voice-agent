---
id: sip-testing-environment
name: SIP Testing Environment
type: Feature
priority: P1
effort: Large
impact: Medium
created: 2026-02-06
shipped: 2026-02-11
---

# SIP Testing Environment - Shipped

## Summary

Successfully implemented a complete SIP testing environment using EC2-based Asterisk with a web-based interface for testing voice agent SIP integration and call transfers.

**Note:** This feature was implemented in the separate `asset-sip-server` repository and integrated with this project.

## What Was Built

### Infrastructure (asset-sip-server)
- **EC2 Instance**: t3.medium running Amazon Linux 2023
- **Asterisk 20 LTS**: Complete PBX with PJSIP, WebRTC support
- **Security Groups**: Configured for SIP (5060), RTP (10000-20000), HTTP/HTTPS
- **Elastic IP**: Static public IP for consistent access
- **Route 53**: DNS record for easy access
- **CloudWatch**: Logging and monitoring

### Asterisk Configuration
- **PJSIP**: Configured for WebSocket (WebRTC) and UDP transports
- **Multi-user support**: user-a, user-b, user-c endpoints with role-based contexts
- **Daily.co integration**: SIP trunk for voice agent connectivity
- **Transfer support**: REFER handling with dialplan routing
- **Web client endpoints**: WebRTC-enabled endpoints for browser-based calling

### Web Client
- **React + SIP.js**: Browser-based SIP client
- **WebRTC support**: Audio/video calling without softphone installation
- **Multi-user interface**: Support for User A, User B testing scenarios
- **Call controls**: Dial, hangup, mute, hold
- **Real-time logs**: Asterisk log viewing

## Integration with Voice Agent

The SIP testing environment successfully integrates with the voice agent:

1. **User A** calls extension 9 → connects to voice agent via Daily.co
2. **Voice agent** executes transfer tool → sends SIP REFER
3. **Asterisk** receives REFER → routes to User B
4. **User B** receives call via web client

## Testing Results

✅ **End-to-end transfer successful**
- User A connects to voice agent
- Voice agent initiates transfer via SIP REFER
- Transfer completed in ~500ms
- Call successfully reaches User B
- No errors in logs

## Configuration

### SSM Parameters (shared)
- `/voice-agent/sip-server/ip` - SIP server public IP
- `/voice-agent/sip-server/port` - SIP server port (5060)

### Voice Agent Integration
- `TRANSFER_DESTINATION=sip:user-b@<sip-server-ip>:5060`
- SSM parameters auto-resolved during deployment

## Files in This Repository

Reference documentation:
- `docs/features/sip-testing-environment/idea.md` - Initial concept
- `docs/features/sip-testing-environment/plan.md` - Implementation plan
- `docs/features/sip-testing-environment/requirements-analysis.md` - Requirements

## Success Criteria

All criteria met:
- ✅ Web client can place calls to voice agent via SIP
- ✅ Call transfers work end-to-end
- ✅ No softphone installation required
- ✅ System is always available (EC2-based)
- ✅ Documentation is comprehensive
- ✅ Team can run tests independently

## Repository

**Implementation:** `../asset-sip-server`
- Infrastructure: CDK TypeScript
- Asterisk config: Template-based
- Web client: React + SIP.js

## Usage

1. Access web client at SIP server IP
2. Register as User A or User B
3. Dial extension 9 to reach voice agent
4. Request transfer from voice agent
5. Verify call reaches destination user

## Next Steps

The SIP testing environment is now operational and being used for:
- Voice agent transfer testing
- SIP integration validation
- Multi-user call flow testing

Future enhancements tracked in asset-sip-server repository.
