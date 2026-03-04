---
id: agent-call-hangup-mechanism
name: Agent Call Hangup Mechanism
type: Feature
priority: P0
effort: Small
impact: Low
created: 2026-02-06
---

# Agent Call Hangup Mechanism

## Problem Statement
The voice agent currently has no way to programmatically end a call. Once a conversation reaches its natural conclusion (e.g., the customer's issue is resolved, or the agent has completed its task), there is no mechanism for the agent to disconnect the call. This results in:

- Calls remaining open indefinitely until the caller hangs up
- Wasted resources maintaining active connections
- Poor user experience when the conversation has clearly ended
- Potential billing implications for extended call durations

## Proposed Solution
Implement a mechanism that allows the voice agent to hang up on the caller when appropriate. This should include:

1. A tool or function that the LLM can invoke to end the call
2. Logic to determine when it's appropriate to hang up (e.g., after confirming the issue is resolved)
3. Graceful disconnection that plays a closing message before ending the call
4. Proper cleanup of session resources

## Affected Areas
- Pipecat pipeline
- LLM tool calling
- Call session management
- SIP/WebRTC connection handling
