# Seamless Agent Transitions (Remove Transfer Language)

| Field     | Value       |
|-----------|-------------|
| Type      | Enhancement |
| Priority  | P1          |
| Effort    | Small       |
| Impact    | High        |

## Problem Statement

During multi-agent calls, the LLM explicitly announces transfers between specialist agents using phrases like "Let me transfer you to our appointment specialist" or "I'll connect you with our customer management team." This exposes the internal multi-agent architecture to the caller and creates a disjointed experience. The caller should perceive a single continuous conversation with one assistant, not a series of handoffs between different departments.

From test call #4, examples of transfer language:

- "Let me connect you with our technical support team who can help you troubleshoot that issue."
- "I'll transfer you to our appointment specialist who can find you an available time slot."
- "I'm going to transfer you to our appointment specialist who can check available time slots."

The multi-agent orchestration is an implementation detail -- the caller should experience seamless topic shifts, not explicit transfers.

## Observed Behavior

- Orchestrator and specialist agents announce transfers explicitly
- The LLM uses language like "transfer", "connect you with", "our X team/specialist"
- Each new agent re-introduces itself, sometimes repeating its name ("Hello! I'm Alex with customer relationship management")
- The caller hears what feels like being bounced between departments

## Expected Behavior

- No mention of "transfer", "connect you with", "specialist", or "team"
- Topic shifts should feel natural: "I can help with that. Let me look up your account first."
- The agent persona should remain consistent -- same name, same voice, same conversational style
- Context from the previous node should flow naturally without re-introduction
- The "One moment please" transition TTS is acceptable as a brief pause

## Investigation Areas

- `app/flows/nodes/orchestrator.py`: System prompt instructs orchestrator on routing language
- `app/flows/nodes/specialist.py`: Specialist node greeting/role message instructions
- `app/flows/context.py`: Summary prompts that frame the handoff context
- Consider adding explicit instructions like: "Never mention transfers, teams, specialists, or departments. You are one continuous assistant. When switching topics, transition naturally."
- The `RESET_WITH_SUMMARY` context strategy means each node starts fresh -- the summary prompt is the key lever for natural continuity
