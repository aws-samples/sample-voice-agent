---
id: sip-testing-environment
name: SIP Testing Environment
type: Feature
priority: P1
effort: Large
impact: Medium
created: 2026-02-06
---

# SIP Testing Environment

> **MOVED**: This feature has been moved to a separate repository:  
> `/Users/schuettc/Documents/GitHub/ml-frameworks-voice/asset-sip-server`  
> All documentation, implementation plans, and code will be maintained there.

## Original Problem Statement

## Problem Statement

Currently, there is no way to test the voice agent with real SIP (Session Initiation Protocol) calls. We need a testing infrastructure that can:

1. **Receive inbound SIP calls** - A SIP server that can route calls into the voice agent for testing end-to-end call flows
2. **Support call transfers** - Ability to transfer calls out to external destinations (human agents, other systems)
3. **Enable realistic testing** - Test scenarios like barge-in, call routing, transfer flows, and error handling in a production-like environment

Without this infrastructure, we cannot validate:
- SIP integration with the voice agent
- Call transfer functionality
- Real-world call quality and latency
- Failover and error scenarios

## Refined Requirements

### Testing Approach
- **Primary Use Case**: Manual testing of SIP integration
- **Call Volume**: Extremely low (1-2 concurrent calls max)
- **Availability**: Always-on for immediate testing access
- **Cost Sensitivity**: Low - prioritize ease of use and reliability over cost optimization

### Call Sources
- **SIP-to-SIP is sufficient** - No PSTN required for core testing
- **Easy-to-use SIP endpoints** - Must NOT require softphones like Zoiper
- **Web-based client preferred** - Browser-based interface for initiating test calls

### Infrastructure Preferences
- **EC2-based Asterisk** - For ease of use, flexibility, and reliability
- **Reference implementations** - Leverage patterns from Chime SDK GitHub repos
- **Twilio integration** - Reserved for full PSTN access when needed

### Future Considerations
- This may become a **separate repository** as it grows into a standalone testing tool
- Should be designed as a modular, reusable component

## Affected Areas
- Testing infrastructure
- SIP integration
- Call transfer functionality
- Deployment architecture
- Potential new repository creation

## Technical Considerations

### Asterisk Server Requirements

The SIP server needs to handle both inbound and outbound call flows:

**Inbound Call Flow (Testing):**
```
Test Caller (Web Client) → Asterisk → Daily SIP URI → Voice Agent
```

**Outbound Transfer Flow:**
```
Voice Agent → Daily SIP REFER → Asterisk → External Destination (SIP/PSTN via Twilio)
```

**Key Components:**
1. **SIP Trunk Configuration** - Connect Asterisk to Daily.co SIP endpoints
2. **Dialplan Logic** - Route incoming calls to appropriate Daily rooms
3. **REFER Handling** - Process transfer requests from Daily
4. **Media Handling** - RTP/RTCP stream management
5. **Logging** - CDR (Call Detail Records) for test validation

### Call Sources

**For Inbound Testing:**
- WebRTC-based SIP client (built-in web interface)
- Simple browser-based dialer (no softphone installation)
- Optional: Programmatic test scripts for automation

**For Transfer Testing:**
- External SIP endpoints (via Asterisk)
- PSTN numbers via Twilio (when full PSTN testing needed)
- Simulated destinations for validation

### Endpoint Requirements

**Need to Build:**
1. **Web-based SIP Client** - Browser interface for making test calls
2. **SIP Registration Endpoint** - For the web client to register
3. **Dialplan API** - To dynamically route calls to correct Daily rooms
4. **Transfer Handler** - To receive and process REFER requests
5. **Test Control Dashboard** - Web UI for managing tests and viewing logs

**Reference Architecture:**
The [Amazon Chime SDK Click-to-Call sample](https://github.com/aws-samples/amazon-chime-sdk-click-to-call) demonstrates a similar pattern:
- React web client for initiating calls
- Asterisk PBX for SIP testing
- SIP media application for call control
- WebRTC to telephony bridging

While this sample uses Chime SDK (not Daily.co), the architecture patterns are applicable:
- Web client for test initiation
- SIP infrastructure for routing
- Asterisk deployment patterns
- Call control via API endpoints

### Deployment Strategy

**EC2-Based Asterisk (Preferred):**
- Single t3.medium or t3.large instance
- Amazon Linux 2 or Ubuntu LTS
- Persistent EBS storage for configuration and logs
- Security group with SIP (5060), RTP (10000-20000), and SSH (22) access
- Easy to debug, modify, and maintain
- Can be stopped/started as needed

### Integration Points

**Daily.co SIP Integration:**
- Static SIP URI mapping for test environments
- Support for dynamic room creation
- REFER message handling for transfers

**Twilio Integration (Optional):**
- Elastic SIP Trunking for PSTN access
- Used only when full PSTN testing is required
- Pay-per-use model for occasional PSTN calls

## Open Questions

1. **Repository Structure:**
   - Should this be a standalone repo from the start?
   - How to structure it for easy deployment and use?

2. **Web Client Design:**
   - Build from scratch or adapt Chime SDK sample?
   - Should it support multiple concurrent test sessions?
   - Need call recording/playback capabilities?

3. **Asterisk Configuration:**
   - Use PJSIP or chan_sip?
   - Need WebRTC support in Asterisk?
   - Configuration management approach

4. **Transfer Testing Scenarios:**
   - What types of transfers to support (blind, attended)?
   - How to validate transfer success?
   - Need to simulate agent pickup?

5. **Documentation:**
   - How to make this easy for developers to use?
   - Need step-by-step testing guides?
   - Video walkthroughs?
