---
id: sip-testing-environment
name: SIP Testing Environment
type: Feature
priority: P1
effort: Large
impact: Medium
created: 2026-02-06
---

# SIP Testing Environment - Implementation Plan

## Overview

This plan outlines the step-by-step implementation of a SIP testing environment using EC2-based Asterisk. The solution provides a web-based interface for testing voice agent SIP integration and call transfers without requiring softphone installation.

**Estimated Duration:** 6 weeks  
**Team Size:** 1-2 developers  
**Key Decisions:**
- EC2-based Asterisk on t3.medium instance
- React + SIP.js web client
- Python FastAPI backend
- AWS CDK for infrastructure
- Optional Twilio integration for PSTN

---

## Phase 1: Infrastructure Setup (Week 1-2)

### 1.1 Project Structure and Repository Setup

**Tasks:**
- [ ] Create new repository `sip-testing-environment` (decide: separate repo or subdirectory)
- [ ] Set up project structure:
  ```
  sip-testing-environment/
  ├── infrastructure/
  ├── asterisk-config/
  ├── web-client/
  ├── api-server/
  └── docs/
  ```
- [ ] Initialize CDK project with TypeScript
- [ ] Set up git repository with .gitignore
- [ ] Create README with overview and setup instructions

**Deliverables:**
- Repository initialized
- Basic folder structure
- CDK project scaffolded

**Time Estimate:** 4 hours

### 1.2 EC2 Infrastructure (CDK)

**Tasks:**
- [ ] Create VPC with public subnet
- [ ] Set up Security Groups:
  - SSH (22) - restricted to office VPN
  - HTTP (80) - web client
  - HTTPS (443) - web client
  - SIP (5060/5061 TCP/UDP) - SIP signaling
  - RTP (10000-20000 UDP) - media
- [ ] Create EC2 instance:
  - Instance type: t3.medium
  - AMI: Amazon Linux 2023
  - Root volume: 20GB gp3
  - IAM role for SSM access
- [ ] Allocate Elastic IP
- [ ] Set up Route 53 record (optional): `sip-test.yourdomain.com`
- [ ] Create CloudWatch log group

**CDK Stack Components:**
```typescript
// Key resources to implement
- VPC with 1 public subnet
- Internet Gateway
- Security Group with SIP/RTP rules
- EC2 Instance (t3.medium)
- Elastic IP
- IAM Role (SSM, CloudWatch)
```

**Deliverables:**
- CDK stack for infrastructure
- Deployable to dev account
- Security groups configured

**Time Estimate:** 8 hours

### 1.3 Asterisk Installation and Configuration

**Tasks:**
- [ ] Create user-data script for EC2 bootstrap
- [ ] Install Asterisk 20 LTS:
  ```bash
  # Dependencies
  sudo dnf install -y epel-release
  sudo dnf install -y asterisk asterisk-pjsip asterisk-voicemail
  ```
- [ ] Configure PJSIP (`pjsip.conf`):
  - Transport (UDP/TCP/TLS)
  - Endpoint for Daily.co SIP trunk
  - Endpoint for web client registrations
  - AOR (Address of Record) configurations
  - Auth sections
- [ ] Configure dialplan (`extensions.conf`):
  - Context for inbound test calls
  - Context for transfer handling
  - Pattern matching for Daily rooms
- [ ] Configure RTP (`rtp.conf`):
  - Port range: 10000-20000
  - ICE support for WebRTC
- [ ] Configure HTTP (`http.conf`):
  - Enable Asterisk HTTP server
  - Set up for WebSocket (if needed)
- [ ] Set up logging:
  - CDR to CSV
  - SIP debug logging
  - Verbose logging level

**Configuration Files to Create:**
- `asterisk-config/pjsip.conf`
- `asterisk-config/extensions.conf`
- `asterisk-config/rtp.conf`
- `asterisk-config/http.conf`
- `asterisk-config/logger.conf`

**Deliverables:**
- Asterisk configuration files
- Bootstrap script for EC2
- Working Asterisk installation

**Time Estimate:** 12 hours

### 1.4 Initial Deployment and Testing

**Tasks:**
- [ ] Deploy infrastructure with CDK
- [ ] Verify EC2 instance is running
- [ ] SSH into instance and verify Asterisk
- [ ] Test Asterisk CLI: `asterisk -rvvv`
- [ ] Check PJSIP endpoints: `pjsip show endpoints`
- [ ] Verify SIP port is listening: `netstat -tulpn | grep 5060`
- [ ] Test basic SIP connectivity with sipsak or similar

**Deliverables:**
- Running Asterisk server
- Basic SIP connectivity confirmed
- Deployment documented

**Time Estimate:** 4 hours

---

## Phase 2: Web Client Development (Week 2-3)

### 2.1 API Backend Setup

**Tasks:**
- [ ] Set up Python FastAPI project structure
- [ ] Create virtual environment and requirements.txt
- [ ] Implement configuration endpoints:
  - GET /api/config - Get current configuration
  - POST /api/config - Update configuration
- [ ] Implement call control endpoints:
  - POST /api/calls - Initiate call (returns SIP credentials)
  - DELETE /api/calls/{id} - Hang up call
  - GET /api/calls - List active calls
- [ ] Implement logging endpoints:
  - GET /api/logs - Retrieve Asterisk logs
  - GET /api/cdr - Get call detail records
- [ ] Set up CORS for web client
- [ ] Add basic authentication (optional for Phase 1)

**API Endpoints:**
```python
# Key endpoints to implement
GET  /api/health          # Health check
GET  /api/config          # Get configuration
POST /api/config          # Update configuration
POST /api/calls           # Initiate call
DELETE /api/calls/{id}    # Hang up call
GET  /api/calls           # List active calls
GET  /api/logs            # Get logs
GET  /api/cdr             # Get CDR records
```

**Deliverables:**
- FastAPI application
- API documentation (auto-generated)
- Configuration management

**Time Estimate:** 8 hours

### 2.2 React Web Client Setup

**Tasks:**
- [ ] Initialize React project with Vite or Create React App
- [ ] Install dependencies:
  - SIP.js for WebRTC/SIP
  - Material-UI or Tailwind CSS
  - Axios for API calls
- [ ] Set up project structure:
  ```
  web-client/src/
  ├── components/
  │   ├── DialPad/
  │   ├── CallControls/
  │   ├── CallStatus/
  │   ├── AudioVisualizer/
  │   └── LogsPanel/
  ├── hooks/
  │   └── useSIP.js
  ├── services/
  │   ├── api.js
  │   └── sip.js
  └── App.jsx
  ```
- [ ] Configure environment variables:
  - API_BASE_URL
  - WS_URL (for WebSocket if needed)

**Deliverables:**
- React project scaffolded
- Dependencies installed
- Development environment ready

**Time Estimate:** 4 hours

### 2.3 SIP.js Integration

**Tasks:**
- [ ] Create SIP service module
- [ ] Implement SIP user agent configuration:
  ```javascript
  const userAgent = new SIP.UserAgent({
    uri: SIP.UserAgent.makeURI(`sip:${username}@${server}`),
    transportOptions: { server: `wss://${server}:8443/ws` },
    registererOptions: { ... }
  });
  ```
- [ ] Implement registration handling
- [ ] Implement call initiation:
  - Create INVITE
  - Handle 100 Trying, 180 Ringing, 200 OK
  - Set up media (getUserMedia)
  - Handle SDP negotiation
- [ ] Implement call termination
- [ ] Handle incoming calls (for transfer testing)
- [ ] Implement re-INVITE handling (for transfers)

**SIP.js Components:**
- UserAgent (main SIP stack)
- Registerer (registration)
- Inviter (outgoing calls)
- Invitation (incoming calls)
- Session (call management)

**Deliverables:**
- SIP service module
- Call establishment working
- Media (audio) flowing

**Time Estimate:** 12 hours

### 2.4 UI Components

**Tasks:**
- [ ] Create DialPad component:
  - Numeric keypad
  - Call button
  - Clear/Backspace
  - Display for entered number
- [ ] Create CallControls component:
  - Hang up button
  - Mute/unmute
  - Hold/resume
  - Transfer (for Phase 4)
- [ ] Create CallStatus component:
  - Connection state (idle, connecting, connected, disconnected)
  - Call duration timer
  - Audio level indicator
- [ ] Create AudioVisualizer component:
  - Real-time audio waveform
  - Input/output level meters
- [ ] Create ConfigurationPanel component:
  - Daily room selection
  - SIP credentials input
  - Transfer destinations
- [ ] Create LogsPanel component:
  - Real-time log display
  - Filter/search capabilities
  - Export functionality

**UI Layout:**
```
┌─────────────────────────────────────┐
│  SIP Testing Environment     [Menu] │
├─────────────────────────────────────┤
│  ┌──────────┐  ┌─────────────────┐ │
│  │          │  │   Call Status   │ │
│  │  Dial    │  │  ┌───────────┐  │ │
│  │  Pad     │  │  │ Connected │  │ │
│  │          │  │  │ 00:02:15  │  │ │
│  │ [1][2][3]│  │  └───────────┘  │ │
│  │ [4][5][6]│  │                 │ │
│  │ [7][8][9]│  │ [Hang Up]       │ │
│  │ [*][0][#]│  │ [Mute] [Hold]   │ │
│  │          │  │                 │ │
│  │ [Call]   │  │ [Audio Visual]  │ │
│  └──────────┘  └─────────────────┘ │
├─────────────────────────────────────┤
│  Configuration    │    Logs         │
│  [Room: ____]     │    [Real-time]  │
│  [Credentials]    │    [Search...]  │
└─────────────────────────────────────┘
```

**Deliverables:**
- All UI components
- Responsive design
- Basic styling

**Time Estimate:** 16 hours

### 2.5 Integration and Testing

**Tasks:**
- [ ] Integrate API backend with web client
- [ ] Test end-to-end flow:
  1. Open web client
  2. Configure Daily room
  3. Enter extension
  4. Click call
  5. Verify SIP registration
  6. Verify call connects
  7. Verify audio flows
  8. Hang up
- [ ] Test error scenarios:
  - Invalid SIP URI
  - Network failure
  - Authentication failure
  - Busy signal
- [ ] Cross-browser testing (Chrome, Firefox, Safari)

**Deliverables:**
- Working web client
- End-to-end call flow tested
- Bug fixes applied

**Time Estimate:** 8 hours

---

## Phase 3: Daily.co Integration (Week 3-4)

### 3.1 Daily.co SIP Configuration

**Tasks:**
- [ ] Obtain Daily.co SIP credentials:
  - SIP URI format
  - Authentication details
  - Domain information
- [ ] Configure PJSIP trunk in Asterisk:
  ```ini
  [daily-trunk]
  type=endpoint
  transport=transport-udp
  context=from-daily
  disallow=all
  allow=ulaw,alaw
  auth=daily-auth
  aors=daily-aors
  
  [daily-auth]
  type=auth
  auth_type=userpass
  username=<daily-username>
  password=<daily-password>
  
  [daily-aors]
  type=aor
  contact=sip:<daily-domain>
  ```
- [ ] Configure dialplan for Daily routing:
  ```ini
  [to-daily]
  exten => _X.,1,NoOp(Routing to Daily room: ${EXTEN})
  same => n,Dial(PJSIP/${EXTEN}@daily-trunk,30)
  same => n,Hangup()
  ```
- [ ] Test SIP trunk registration
- [ ] Verify connectivity with Daily.co

**Deliverables:**
- Daily.co SIP trunk configured
- Registration successful
- Test call to Daily works

**Time Estimate:** 6 hours

### 3.2 Dynamic Room Routing

**Tasks:**
- [ ] Implement room configuration in API:
  - Store room mappings (extension -> Daily room)
  - Support multiple environments (dev, staging)
- [ ] Update dialplan for dynamic routing:
  - Use Asterisk database or AGI script
  - Lookup room based on extension
- [ ] Update web client:
  - Room selection dropdown
  - Show available rooms
  - Configure new rooms
- [ ] Test with multiple Daily rooms

**Deliverables:**
- Dynamic room routing
- Multiple room support
- Configuration UI

**Time Estimate:** 6 hours

### 3.3 End-to-End Testing

**Tasks:**
- [ ] Deploy voice agent to test environment
- [ ] Configure Daily room for testing
- [ ] Place test call:
  1. Open web client
  2. Select Daily room
  3. Dial extension
  4. Call connects to voice agent
  5. Interact with agent
  6. Verify audio quality
- [ ] Test various scenarios:
  - Different Daily rooms
  - Long-duration calls
  - Multiple concurrent calls
  - Call with barge-in

**Deliverables:**
- Successful end-to-end testing
- Voice agent integration validated
- Documentation of test results

**Time Estimate:** 6 hours

---

## Phase 4: Transfer Testing (Week 4-5)

### 4.1 REFER Support in Asterisk

**Tasks:**
- [ ] Verify Asterisk REFER support
- [ ] Configure transfer context in dialplan:
  ```ini
  [transfer-handler]
  exten => _X.,1,NoOp(Handling transfer to: ${EXTEN})
  same => n,Dial(PJSIP/${EXTEN}@transfer-dest,30)
  same => n,Hangup()
  ```
- [ ] Set up transfer destinations:
  - External SIP endpoints
  - PSTN numbers (via Twilio)
- [ ] Configure PJSIP for transfer destinations
- [ ] Test REFER handling with sipp or similar tool

**Deliverables:**
- REFER support configured
- Transfer destinations defined
- Test tools ready

**Time Estimate:** 8 hours

### 4.2 Transfer Destinations

**Tasks:**
- [ ] Configure external SIP endpoints:
  - Create test endpoints (other softphones or Asterisk)
  - Configure in PJSIP
- [ ] Set up Twilio Elastic SIP Trunk (optional):
  - Create Twilio account/subaccount
  - Configure Elastic SIP Trunk
  - Add Asterisk IP to allowed list
  - Configure credentials
- [ ] Update API to manage transfer destinations:
  - CRUD operations for destinations
  - Destination types (SIP, PSTN)
- [ ] Update web client:
  - Transfer destination management
  - UI for initiating transfers

**Transfer Configuration:**
```json
{
  "destinations": [
    {
      "id": "external-sip-1",
      "name": "Test Extension 100",
      "type": "sip",
      "uri": "sip:100@external-server.com"
    },
    {
      "id": "twilio-pstn",
      "name": "PSTN via Twilio",
      "type": "pstn",
      "number": "+1234567890"
    }
  ]
}
```

**Deliverables:**
- Transfer destinations configured
- API for destination management
- Web UI updated

**Time Estimate:** 8 hours

### 4.3 Transfer Testing Implementation

**Tasks:**
- [ ] Update voice agent transfer tool to use SIP REFER
- [ ] Test blind transfer:
  1. Caller connects to voice agent
  2. Voice agent initiates transfer
  3. Asterisk receives REFER
  4. Call transfers to destination
  5. Original call ends
- [ ] Test attended transfer (if supported):
  1. Voice agent places destination on hold
  2. Consultation call to destination
  3. Complete transfer
- [ ] Validate transfer success/failure:
  - Log transfer events
  - Report status to voice agent
  - Handle errors gracefully

**Deliverables:**
- Transfer functionality working
- Test scenarios validated
- Error handling implemented

**Time Estimate:** 8 hours

### 4.4 Transfer Validation and Logging

**Tasks:**
- [ ] Enhance logging for transfers:
  - Log REFER received
  - Log transfer attempt
  - Log transfer result
  - Log errors
- [ ] Update web client to show transfer status:
  - Real-time transfer notifications
  - Transfer history
  - Success/failure indicators
- [ ] Create transfer test scenarios:
  - Successful transfer to SIP endpoint
  - Successful transfer to PSTN
  - Failed transfer (busy, unreachable)
  - Transfer timeout
- [ ] Document transfer testing procedures

**Deliverables:**
- Comprehensive transfer logging
- Web UI for transfer monitoring
- Test scenarios documented

**Time Estimate:** 6 hours

---

## Phase 5: Polish and Documentation (Week 5-6)

### 5.1 UI/UX Improvements

**Tasks:**
- [ ] Improve visual design:
  - Consistent color scheme
  - Better typography
  - Responsive layout
- [ ] Add user feedback:
  - Toast notifications for actions
  - Loading states
  - Error messages
- [ ] Enhance call controls:
  - Volume control
  - Device selection (microphone/speaker)
  - Call timer display
- [ ] Add keyboard shortcuts
- [ ] Implement dark mode (optional)

**Deliverables:**
- Polished UI
- Better user experience
- Professional appearance

**Time Estimate:** 10 hours

### 5.2 Monitoring and Alerting

**Tasks:**
- [ ] Set up CloudWatch dashboards:
  - EC2 CPU/memory metrics
  - Network I/O
  - SIP port availability
- [ ] Create CloudWatch alarms:
  - High CPU utilization
  - Instance health check failures
  - SIP port unreachable
- [ ] Add application metrics:
  - Active call count
  - Call success/failure rate
  - Average call duration
- [ ] Set up SNS notifications for alerts
- [ ] Create runbook for common issues

**Deliverables:**
- CloudWatch dashboards
- Alerting configured
- Runbook created

**Time Estimate:** 6 hours

### 5.3 Security Hardening

**Tasks:**
- [ ] Review and tighten security groups
- [ ] Implement IP whitelisting for SIP
- [ ] Set up fail2ban for brute force protection
- [ ] Enable Asterisk security features:
  - ACLs for endpoints
  - Rate limiting
  - Authentication enforcement
- [ ] Configure HTTPS with Let's Encrypt
- [ ] Review and rotate credentials
- [ ] Security audit and penetration testing (basic)

**Deliverables:**
- Security hardening applied
- HTTPS enabled
- Audit completed

**Time Estimate:** 8 hours

### 5.4 Documentation

**Tasks:**
- [ ] Write comprehensive README:
  - Project overview
  - Architecture diagram
  - Quick start guide
- [ ] Create SETUP.md:
  - Prerequisites
  - Step-by-step deployment
  - Configuration details
- [ ] Create USAGE.md:
  - How to use the web client
  - Testing procedures
  - Troubleshooting guide
- [ ] Create ARCHITECTURE.md:
  - System design
  - Component interactions
  - Data flow diagrams
- [ ] Document Asterisk configuration:
  - PJSIP setup
  - Dialplan logic
  - Customization guide
- [ ] Create API documentation:
  - Endpoint reference
  - Authentication
  - Example requests/responses
- [ ] Add inline code comments
- [ ] Create video walkthrough (optional)

**Documentation Structure:**
```
docs/
├── README.md              # Project overview
├── SETUP.md              # Deployment guide
├── USAGE.md              # User guide
├── ARCHITECTURE.md       # Technical design
├── ASTERISK.md           # Asterisk configuration
├── API.md                # API reference
├── TESTING.md            # Testing procedures
└── TROUBLESHOOTING.md    # Common issues
```

**Deliverables:**
- Complete documentation
- User guides
- Technical documentation

**Time Estimate:** 12 hours

### 5.5 Final Testing and Validation

**Tasks:**
- [ ] Perform comprehensive testing:
  - All test scenarios from Phase 3
  - Transfer scenarios from Phase 4
  - Error scenarios
  - Edge cases
- [ ] Load testing (limited):
  - 2-3 concurrent calls
  - Verify stability
- [ ] Security testing:
  - Verify authentication
  - Test access controls
- [ ] Cross-browser testing
- [ ] Mobile device testing (if applicable)
- [ ] Create test report

**Deliverables:**
- Test results documented
- Issues resolved
- Sign-off from stakeholders

**Time Estimate:** 8 hours

---

## Summary Timeline

| Phase | Duration | Key Deliverables |
|-------|----------|------------------|
| Phase 1: Infrastructure | Week 1-2 | EC2 + Asterisk running |
| Phase 2: Web Client | Week 2-3 | React app + SIP.js working |
| Phase 3: Daily Integration | Week 3-4 | End-to-end calls working |
| Phase 4: Transfer Testing | Week 4-5 | Transfers validated |
| Phase 5: Polish & Docs | Week 5-6 | Production-ready system |

**Total Estimated Effort:** 6 weeks (1 developer) or 3-4 weeks (2 developers)

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Asterisk complexity | Start with basic config, iterate |
| WebRTC compatibility | Test early, have fallback |
| Daily.co SIP issues | Maintain good communication with Daily |
| Scope creep | Focus on manual testing first |
| Security concerns | Implement security early, audit often |

---

## Success Criteria

- [ ] Web client can place calls to voice agent via SIP
- [ ] Call transfers work end-to-end
- [ ] No softphone installation required
- [ ] System is always available
- [ ] Documentation is comprehensive
- [ ] Team can run tests independently

---

## Next Steps

1. **Decision Point:** Create separate repository or subdirectory?
2. **Setup:** Initialize project and CDK
3. **Begin:** Phase 1 - Infrastructure setup
4. **Review:** Progress after each phase
5. **Iterate:** Adjust plan based on learnings
