# Call Transfers

The voice agent can transfer active calls to human agents or other SIP endpoints via SIP REFER. This feature is **optional** and disabled by default.

## How It Works

1. During a conversation, the LLM decides a transfer is needed (e.g., "Let me transfer you to a specialist")
2. The voice agent invokes the `transfer_to_agent` tool
3. The tool sends a SIP REFER through the Daily.co transport
4. Daily.co bridges the caller to the specified SIP URI
5. The voice agent disconnects from the call

## Prerequisites

- `ENABLE_TOOL_CALLING` must be `true` (via SSM or environment variable)
- A SIP endpoint that can accept incoming calls (PBX, SIP phone, SIP trunking service, etc.)

## Configuration

Set the `TRANSFER_DESTINATION` to a SIP URI. This can be done via CDK context or environment variable.

### Option A: CDK Context (Recommended)

```bash
npx cdk deploy VoiceAgentEcs \
  -c voice-agent:transferDestination="sip:agent@your-pbx.example.com:5060"
```

### Option B: Environment Variable

```bash
TRANSFER_DESTINATION="sip:agent@your-pbx.example.com:5060" npx cdk deploy VoiceAgentEcs
```

After deploying, the voice agent's capability-based tool system automatically detects `TRANSFER_DESTINATION` and registers the `transfer_to_agent` tool. No code changes are needed.

## SIP Endpoint Examples

The transfer destination can be any SIP-capable endpoint:

| Endpoint Type | Example SIP URI |
|---------------|----------------|
| IP-based PBX | `sip:extension@192.168.1.100:5060` |
| DNS-based PBX | `sip:agent@pbx.example.com:5060` |
| SIP Trunking (Twilio) | `sip:+15551234567@your-trunk.pstn.twilio.com` |
| SIP Trunking (Vonage) | `sip:+15551234567@sip.nexmo.com` |
| FreeSWITCH | `sip:1002@freeswitch.example.com:5060` |
| Asterisk PBX | `sip:user-b@asterisk.example.com:5060` |

## Disabling Transfers

To disable transfers, simply don't set `TRANSFER_DESTINATION`. The capability-based tool system will not register the `transfer_to_agent` tool, and the LLM will not offer to transfer calls.

You can also explicitly disable the tool via SSM:
```bash
aws ssm put-parameter \
  --name "/voice-agent/config/disabled-tools" \
  --value "transfer_to_agent" \
  --type String \
  --overwrite
```

## How the Capability System Works

The voice agent uses a capability-based tool registration system. The `transfer_to_agent` tool declares these requirements:

| Capability | Detected When |
|------------|--------------|
| `TRANSPORT` | DailyTransport is present in the pipeline |
| `SIP_SESSION` | Pipeline has an active SIP dial-in tracker |
| `TRANSFER_DESTINATION` | `TRANSFER_DESTINATION` environment variable is set |

All three must be satisfied for the tool to be registered. This means transfers only work for:
- Calls that come in via SIP/PSTN (not browser-only WebRTC sessions)
- Deployments where a transfer destination is configured

## Troubleshooting

### Transfer Tool Not Appearing

1. Verify `ENABLE_TOOL_CALLING` is `true`
2. Check that `TRANSFER_DESTINATION` is set in the ECS task environment:
   ```bash
   aws ecs describe-task-definition --task-definition <task-def-arn> \
     --query 'taskDefinition.containerDefinitions[0].environment'
   ```
3. Ensure the call came in via SIP (not a browser WebRTC join)

### Transfer Fails with "SIP REFER Not Supported"

- The Daily.co room must have `sip_mode: "dial-in"` enabled. This is configured automatically by the bot-runner Lambda.

### Transferred Call Drops Immediately

- Verify the SIP endpoint is reachable from Daily.co's infrastructure
- Check that the SIP endpoint accepts the incoming INVITE
- Ensure the SIP URI format is correct (including port number)
