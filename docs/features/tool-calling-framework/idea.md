---
name: Tool Calling Framework
type: feature
priority: P0
effort: large
impact: high
status: idea
created: 2026-01-27
---

# Tool Calling Framework

## Problem Statement

The voice agent currently only generates conversational text responses. To be useful for customer support, it needs to execute real actions: look up customer accounts, check order status, query databases, interact with calendar/booking systems, and create CRM tickets. Without tool calling, the agent cannot provide personalized, actionable assistance.

## Proposed Solution

Implement a tool calling framework that:
1. Defines a structured format for tool definitions (name, description, parameters, return schema)
2. Parses tool calls from Claude's responses using the Bedrock Converse API tool_use blocks
3. Executes tools safely with timeout handling and error recovery
4. Returns tool results back to the LLM for natural language synthesis

## Technical Approach

### Tool Definition Registry
- Create a `ToolRegistry` class to register available tools
- Each tool has: name, description, JSON schema for parameters, async executor function
- Tools are registered at pipeline startup based on deployment configuration

### Tool Parsing in Bedrock LLM Service
- Modify `bedrock_llm.py` to include tool definitions in Converse API requests
- Parse `tool_use` content blocks from responses
- Handle streaming with tool calls (buffer until complete)

### Tool Executor Framework
- Async executor with configurable timeouts per tool
- Error handling with graceful degradation (inform user if tool fails)
- Audit logging of all tool invocations for compliance

### Pipeline Integration
- Insert tool execution step between LLM response and TTS
- Coordinate with conversational-delay-handling feature for long-running tools

## Affected Areas

- `backend/voice-agent/app/services/bedrock_llm.py` - Add tool parsing and API integration
- `backend/voice-agent/app/pipeline_ecs.py` - Tool execution in pipeline flow
- New: `backend/voice-agent/app/tools/` - Tool definitions and executor framework
- New: `backend/voice-agent/app/tools/registry.py` - Tool registration
- New: `backend/voice-agent/app/tools/executor.py` - Safe async tool execution

## Example Tools (Initial Set)

1. **get_customer_info** - Look up customer by phone number or account ID
2. **check_order_status** - Query order status from order management system
3. **create_support_ticket** - Create a ticket in CRM system
4. **transfer_to_agent** - Escalate to human agent with context

## Success Criteria

- [ ] Tool definitions can be registered declaratively
- [ ] Claude correctly invokes tools based on conversation context
- [ ] Tool results are incorporated into natural responses
- [ ] Failed tools result in graceful user-facing error messages
- [ ] All tool invocations are logged for audit purposes

## Dependencies

- Bedrock Converse API tool_use support (available)
- External service integrations for actual tool implementations

## Related Features

- `conversational-delay-handling` - Handle delays during tool execution
- `knowledge-base-rag` - RAG could be implemented as a tool
