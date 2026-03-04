---
id: smart-transfer-tool
name: Smart Transfer Tool
type: Feature
priority: P0
effort: Medium
impact: High
created: 2026-02-02
started: 2026-02-10
---

# Smart Transfer Tool - Implementation Plan

## Overview

Implement minimal viable call transfer functionality using Daily's SIP REFER capability. This is the foundational transfer feature that enables the voice agent to transfer calls to human agents via SIP.

**Goal**: Get basic cold transfers working end-to-end with the SIP testing environment.

## Implementation Steps

### Phase 1: Update Transfer Tool (MVP) ✅ COMPLETE

**1.1 Modify transfer_tool.py** ✅
- [x] Add transport reference to tool context
- [x] Implement actual SIP REFER call using DailyTransport
- [x] Add hardcoded destination for SIP server User B
- [x] Handle success/failure responses
- [x] Return appropriate messages to user

**1.2 Update ToolContext** ✅
- [x] Add transport field to ToolContext dataclass
- [x] Pass transport from pipeline to tool execution

**1.3 Update Pipeline Registration** ✅
- [x] Modify _register_tools() to pass transport instance
- [x] Ensure transport is available during tool execution

**1.4 Add Configuration** ✅
- [x] Environment variable for default transfer destination (`TRANSFER_DESTINATION`)
- [x] Document in CLAUDE.md

### Phase 2: Test with SIP Server

**2.1 Configure SIP Server for REFER**
- Enable res_pjsip_refer module
- Update pjsip.conf with allow_transfer
- Add transfer context to extensions.conf

**2.2 End-to-End Testing**
- Place call via SIP server to voice agent
- Trigger transfer from voice agent
- Verify call reaches User B
- Test failure scenarios

### Phase 3: Error Handling & Polish

**3.1 Error Handling**
- Handle transfer timeout
- Handle destination unreachable
- Handle busy signal
- Return appropriate error messages

**3.2 Observability**
- Log transfer attempts
- Track transfer success/failure
- Add CloudWatch metrics

## Files to Modify

1. `/backend/voice-agent/app/tools/builtin/transfer_tool.py` - Main implementation
2. `/backend/voice-agent/app/tools/context.py` - Add transport field
3. `/backend/voice-agent/app/pipeline_ecs.py` - Pass transport to tools
4. `/backend/voice-agent/app/tools/schema.py` - (if needed)

## Dependencies

- DailyTransport with sip_refer() method (available in pipecat)
- SIP server configured to receive transfers
- Environment variables for configuration

## Success Criteria

- [ ] Voice agent can initiate transfer via tool call
- [ ] Call successfully transfers to SIP server User B
- [ ] User receives confirmation message
- [ ] Failed transfers are handled gracefully
- [ ] Events logged for debugging

## Notes

- Start with hardcoded destination to SIP server User B (sip:user-b@sip-server-ip)
- Cold transfer only (SIP REFER) for MVP
- Context packaging deferred to follow-up feature
- Warm transfer deferred to follow-up feature
