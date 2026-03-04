---
id: sip-testing-environment
name: SIP Testing Environment
type: Feature
priority: P1
effort: Large
impact: Medium
created: 2026-02-06
---

# SIP Testing Environment - Requirements Analysis

## Executive Summary

This document provides a comprehensive analysis of requirements for building a SIP (Session Initiation Protocol) testing environment to validate voice agent SIP integration and call transfer functionality. The solution will be built as a standalone testing infrastructure, potentially as a separate repository, using EC2-based Asterisk for reliability and ease of use.

## 1. Business Requirements

### 1.1 Problem Statement
The voice agent currently lacks a way to test SIP integration in realistic scenarios. Without proper testing infrastructure, we cannot validate:
- SIP signaling compatibility with Daily.co
- Call transfer functionality (SIP REFER handling)
- End-to-end call flows
- Error handling and failover scenarios
- Audio quality over SIP

### 1.2 Success Criteria
- Ability to place test calls to the voice agent via SIP
- Support for testing call transfers to external destinations
- Easy-to-use interface that doesn't require softphone installation
- Always-available testing environment
- Comprehensive logging for debugging

## 2. Functional Requirements

### 2.1 Core Capabilities

#### FR-001: Inbound SIP Testing
**Priority:** P0 (Must Have)
**Description:** The system must support placing inbound SIP calls to the voice agent
**Acceptance Criteria:**
- Web-based interface for initiating SIP calls
- Calls route through Asterisk to Daily.co SIP endpoints
- Support for multiple Daily rooms/environments
- Call duration limits to prevent runaway costs
- Ability to hang up calls from the web interface

#### FR-002: Call Transfer Testing
**Priority:** P0 (Must Have)
**Description:** The system must support testing call transfers from the voice agent
**Acceptance Criteria:**
- Handle SIP REFER messages from Daily.co
- Route transfers to configurable external destinations
- Support both SIP and PSTN destinations (via Twilio)
- Provide confirmation of transfer success/failure
- Log transfer events for analysis

#### FR-003: Web-Based Test Client
**Priority:** P0 (Must Have)
**Description:** Browser-based interface for testers to initiate and manage calls
**Acceptance Criteria:**
- No softphone installation required
- Support for microphone access via WebRTC
- Simple dial pad interface
- Call status display (connecting, connected, disconnected)
- Audio level indicators
- Call history/logs display

#### FR-004: Test Configuration Management
**Priority:** P1 (Should Have)
**Description:** Ability to configure test scenarios and parameters
**Acceptance Criteria:**
- Configure target Daily rooms/SIP URIs
- Set up transfer destinations
- Save and load test profiles
- Environment-specific configurations (dev, staging)

#### FR-005: Call Logging and Debugging
**Priority:** P1 (Should Have)
**Description:** Comprehensive logging for troubleshooting
**Acceptance Criteria:**
- Asterisk CDR (Call Detail Records)
- SIP message traces
- Audio quality metrics (if possible)
- Web interface for viewing logs
- Export logs for sharing

### 2.2 Testing Scenarios

#### TS-001: Basic Call Flow
1. Tester opens web client
2. Selects target Daily room/environment
3. Initiates SIP call
4. Voice agent answers
5. Conversation occurs
6. Tester hangs up

#### TS-002: Call Transfer - External SIP
1. Tester initiates call to voice agent
2. Voice agent triggers transfer via tool
3. Asterisk receives REFER
4. Call transfers to external SIP endpoint
5. Transfer success/failure reported

#### TS-003: Call Transfer - PSTN via Twilio
1. Tester initiates call to voice agent
2. Voice agent triggers transfer
3. Asterisk routes to Twilio SIP trunk
4. Call connects to PSTN number
5. Transfer validated

#### TS-004: Error Scenarios
- Invalid SIP URI
- Unreachable destination
- Transfer timeout
- Authentication failures
- Network interruptions

## 3. Non-Functional Requirements

### 3.1 Performance Requirements

#### NFR-001: Call Latency
**Requirement:** End-to-end call setup latency < 5 seconds
**Rationale:** Reasonable user experience for testing

#### NFR-002: Concurrent Calls
**Requirement:** Support 1-2 concurrent test calls
**Rationale:** Low volume manual testing only

#### NFR-003: Availability
**Requirement:** 99% uptime during business hours
**Rationale:** Always-on for ad-hoc testing

### 3.2 Security Requirements

#### NFR-004: SIP Authentication
**Requirement:** All SIP endpoints must be authenticated
**Implementation:** SIP digest authentication with strong passwords

#### NFR-005: Network Security
**Requirement:** Restrict SIP access to authorized IPs
**Implementation:** Security groups and ACLs

#### NFR-006: Web Client Security
**Requirement:** HTTPS for web interface
**Implementation:** TLS certificate (Let's Encrypt or ACM)

### 3.3 Operational Requirements

#### NFR-007: Deployment Simplicity
**Requirement:** One-command or automated deployment
**Implementation:** CDK or CloudFormation template

#### NFR-008: Configuration Management
**Requirement:** Infrastructure as code
**Implementation:** CDK with configuration files

#### NFR-009: Monitoring
**Requirement:** Basic health checks and alerting
**Implementation:** CloudWatch alarms for instance health

#### NFR-010: Backup and Recovery
**Requirement:** Configuration backup
**Implementation:** Version-controlled configs, AMI backups

## 4. Architecture Decisions

### 4.1 Technology Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| SIP Server | Asterisk 20 LTS | Industry standard, well-documented, flexible |
| OS | Amazon Linux 2023 | AWS optimized, good Asterisk support |
| Web Client | React + SIP.js | Modern framework, good WebRTC support |
| Backend API | Python FastAPI | Lightweight, easy to develop |
| Infrastructure | AWS CDK | Infrastructure as code, version controlled |
| PSTN Gateway | Twilio Elastic SIP | Pay-per-use, reliable, easy integration |

### 4.2 Deployment Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      AWS VPC                                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                 Public Subnet                        │  │
│  │  ┌──────────────────────────────────────────────┐   │  │
│  │  │         EC2 Instance (t3.medium)             │   │  │
│  │  │  ┌──────────────┐  ┌──────────────────────┐  │   │  │
│  │  │  │   Asterisk   │  │   Web Server (API)   │  │   │  │
│  │  │  │   (SIP/5060) │  │   (HTTP/HTTPS)       │  │   │  │
│  │  │  └──────────────┘  └──────────────────────┘  │   │  │
│  │  │  ┌──────────────────────────────────────────┐  │   │  │
│  │  │  │      React Web Client (Static)           │  │   │  │
│  │  │  └──────────────────────────────────────────┘  │   │  │
│  │  └──────────────────────────────────────────────┘   │  │
│  └──────────────────────────────────────────────────────┘  │
│                          │                                  │
│              ┌───────────┴───────────┐                     │
│              │                       │                     │
│              ▼                       ▼                     │
│  ┌──────────────────┐    ┌──────────────────┐             │
│  │   Daily.co SIP   │    │  Twilio SIP      │             │
│  │   Endpoint       │    │  Trunk (PSTN)    │             │
│  └──────────────────┘    └──────────────────┘             │
└─────────────────────────────────────────────────────────────┘
```

### 4.3 Asterisk Configuration Strategy

#### PJSIP Configuration
- Use PJSIP (not chan_sip) - more modern, better WebRTC support
- Separate endpoints for:
  - Web client registrations
  - Daily.co SIP trunk
  - External transfer destinations

#### Dialplan Structure
```
extensions.conf:
  [testing-inbound]
    exten => _X.,1,NoOp(Inbound test call)
    same => n,Dial(PJSIP/${EXTEN}@daily-trunk)
    same => n,Hangup()

  [testing-transfer]
    exten => _X.,1,NoOp(Transfer call)
    same => n,Dial(PJSIP/${EXTEN}@transfer-dest)
    same => n,Hangup()
```

#### Media Handling
- RTP port range: 10000-20000
- Codec support: G.711 (μ-law, A-law), optional G.722 for HD audio
- DTLS-SRTP for WebRTC calls

### 4.4 Web Client Architecture

#### Frontend (React)
- SIP.js for WebRTC/SIP handling
- Material-UI or Tailwind for components
- Real-time call status updates

#### Backend API (FastAPI)
- Configuration endpoints (rooms, destinations)
- Call control (initiate, hangup)
- Logs and metrics retrieval
- WebSocket for real-time updates

#### Static Hosting
- Serve React app from EC2 (nginx)
- Or: S3 + CloudFront (if separated)

## 5. Integration Points

### 5.1 Daily.co Integration

#### SIP URI Format
```
sip:<room-name>@<daily-sip-domain>
```

#### Authentication
- SIP digest authentication
- Credentials provided by Daily.co

#### REFER Handling
- Asterisk must support SIP REFER method
- Parse Refer-To header
- Initiate new call leg
- Bridge or replace call as appropriate

### 5.2 Twilio Integration (Optional)

#### Elastic SIP Trunking
- Configure trunk in Twilio Console
- Add Asterisk IP to allowed list
- Use for PSTN calls only when needed

#### Cost Considerations
- ~$0.005/minute for US calls
- Minimal usage expected
- Enable only when PSTN testing required

## 6. Repository Structure

Proposed structure if created as standalone repo:

```
sip-testing-environment/
├── README.md
├── ARCHITECTURE.md
├── infrastructure/
│   ├── cdk/
│   │   ├── bin/
│   │   ├── lib/
│   │   ├── test/
│   │   └── cdk.json
│   └── packer/
│       └── asterisk-ami.json
├── asterisk-config/
│   ├── pjsip.conf
│   ├── extensions.conf
│   ├── rtp.conf
│   └── http.conf
├── web-client/
│   ├── public/
│   ├── src/
│   ├── package.json
│   └── README.md
├── api-server/
│   ├── app/
│   ├── requirements.txt
│   └── Dockerfile
├── scripts/
│   ├── deploy.sh
│   ├── configure-asterisk.sh
│   └── test-call.sh
└── docs/
    ├── SETUP.md
    ├── USAGE.md
    └── TESTING.md
```

## 7. Implementation Phases

### Phase 1: Core Infrastructure (Week 1-2)
- [ ] EC2 instance setup with Asterisk
- [ ] Basic SIP configuration
- [ ] Security groups and networking
- [ ] Initial CDK deployment

### Phase 2: Web Client (Week 2-3)
- [ ] React app setup
- [ ] SIP.js integration
- [ ] Basic call interface
- [ ] API backend

### Phase 3: Daily.co Integration (Week 3-4)
- [ ] SIP trunk configuration
- [ ] Dialplan for routing
- [ ] Test inbound calls
- [ ] Configuration management

### Phase 4: Transfer Testing (Week 4-5)
- [ ] REFER support
- [ ] Transfer destinations
- [ ] Twilio integration (optional)
- [ ] Transfer validation

### Phase 5: Polish and Documentation (Week 5-6)
- [ ] Web UI improvements
- [ ] Logging and debugging
- [ ] Documentation
- [ ] Testing guides

## 8. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Asterisk complexity | Medium | Use proven configurations, start simple |
| WebRTC compatibility | Medium | Test across browsers, fallback options |
| Daily.co SIP changes | Low | Monitor Daily docs, flexible config |
| Security exposure | Medium | Restrict IPs, strong auth, regular updates |
| Cost overruns | Low | Instance limits, monitoring, alerts |

## 9. Success Metrics

- **Time to first test call:** < 2 hours from deployment
- **Test call success rate:** > 95%
- **Transfer success rate:** > 90%
- **Developer satisfaction:** No softphone complaints
- **Adoption:** Used in all SIP-related development

## 10. Future Enhancements

- Automated test scenarios
- Load testing capabilities
- Call recording and playback
- Integration with CI/CD pipelines
- Multi-region deployment
- Advanced analytics dashboard

## 11. References

1. [Amazon Chime SDK Click-to-Call](https://github.com/aws-samples/amazon-chime-sdk-click-to-call)
2. [Asterisk Official Documentation](https://docs.asterisk.org/)
3. [Daily.co SIP Documentation](https://docs.daily.co/guides/integrations/sip)
4. [SIP.js Documentation](https://sipjs.com/)
5. [Twilio Elastic SIP Trunking](https://www.twilio.com/docs/sip-trunking)
