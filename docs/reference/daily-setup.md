# Daily.co Setup Guide

This guide covers setting up Daily.co for PSTN dial-in with the Voice Agent POC.

## Overview

When someone calls your Daily phone number:

1. **Call arrives** → Daily places caller on hold (music plays)
2. **Webhook triggers** → Daily POSTs to your `room_creation_api` endpoint
3. **Room created** → Your backend creates a Daily room + spawns the bot
4. **Bot joins** → Bot connects to room and emits `dialin-ready`
5. **Call connected** → `pinlessCallUpdate` routes the held call to the room
6. **Conversation starts** → Caller and bot can now talk

## Prerequisites

- Daily.co account at [dashboard.daily.co](https://dashboard.daily.co)
- Credit card on file (required for phone numbers)
- Your API key from Daily dashboard

```bash
export DAILY_API_KEY="your-api-key-here"
```

---

## Step 1: Purchase a Phone Number

### 1.1 List Available Numbers

Find available phone numbers in your desired area:

```bash
# List numbers in California (CA)
curl --request GET \
  --url 'https://api.daily.co/v1/list-available-numbers?region=CA' \
  --header "Authorization: Bearer $DAILY_API_KEY"
```

Response:
```json
{
  "total_count": 50,
  "data": [
    {"number": "+14155551234", "region": "CA"},
    {"number": "+14155555678", "region": "CA"},
    ...
  ]
}
```

### 1.2 Buy a Phone Number

Purchase your chosen number:

```bash
curl --request POST \
  --url 'https://api.daily.co/v1/buy-phone-number' \
  --header "Authorization: Bearer $DAILY_API_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "number": "+14155551234"
  }'
```

Response:
```json
{
  "id": "abc123-uuid",
  "number": "+14155551234"
}
```

Save the phone number - you'll need it for the next step.

### 1.3 List Your Phone Numbers

Verify your purchase:

```bash
curl --request GET \
  --url 'https://api.daily.co/v1/phone-numbers' \
  --header "Authorization: Bearer $DAILY_API_KEY"
```

---

## Step 2: Configure Pinless Dial-in

This tells Daily where to send webhook notifications when calls arrive.

### 2.1 Set Up the Webhook

Replace `YOUR_WEBHOOK_URL` with your API Gateway URL:

```bash
curl --request POST \
  --url 'https://api.daily.co/v1' \
  --header "Authorization: Bearer $DAILY_API_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "properties": {
      "pinless_dialin": [
        {
          "phone_number": "+14155551234",
          "room_creation_api": "https://YOUR_API_GATEWAY_URL/webhook"
        }
      ]
    }
  }'
```

Response includes an HMAC secret for webhook verification:
```json
{
  "properties": {
    "pinless_dialin": [
      {
        "phone_number": "+14155551234",
        "room_creation_api": "https://...",
        "hmac": "base64-encoded-secret"
      }
    ]
  }
}
```

**Save the HMAC secret** - use it to verify webhook signatures.

### 2.2 Verify Configuration

Check your domain settings:

```bash
curl --request GET \
  --url 'https://api.daily.co/v1' \
  --header "Authorization: Bearer $DAILY_API_KEY"
```

---

## Step 3: Webhook Handler Requirements

When a call comes in, Daily POSTs to your webhook with:

```json
{
  "To": "+14155551234",
  "From": "+15105559876",
  "callId": "call-uuid-here",
  "callDomain": "your-domain.daily.co"
}
```

Your webhook must:

1. **Return 200 quickly** - Daily expects a fast response
2. **Create a Daily room** with SIP enabled
3. **Spawn the bot** to join that room
4. Wait for `dialin-ready` event
5. **Call `pinlessCallUpdate`** to connect the caller

### Security: Verify Webhook Signature

Daily sends these headers:
- `X-Pinless-Signature` - HMAC-SHA256 signature
- `X-Pinless-Timestamp` - Request timestamp

Verify with:
```python
import hmac
import hashlib
import base64

def verify_signature(body: bytes, signature: str, timestamp: str, hmac_secret: str) -> bool:
    message = f"{timestamp}.{body.decode()}"
    expected = hmac.new(
        base64.b64decode(hmac_secret),
        message.encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
```

---

## Step 4: Connect the Call (pinlessCallUpdate)

After the bot joins and `dialin-ready` fires, connect the caller:

```bash
curl --request POST \
  --url 'https://api.daily.co/v1/pinlessCallUpdate' \
  --header "Authorization: Bearer $DAILY_API_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "callId": "call-uuid-from-webhook",
    "callDomain": "your-domain.daily.co",
    "sipUri": "sip:room-sip-uri@sip.daily.co"
  }'
```

**Important:** Do NOT call `pinlessCallUpdate` before `dialin-ready` - the call will drop!

---

## Alternative: Global Dial-in Numbers (No Purchase Required)

Daily provides shared phone numbers in 27+ countries. Users dial the number and enter a PIN to join a specific room.

Each room gets a unique 11-digit PIN when created:

```bash
# Create a room
curl --request POST \
  --url 'https://api.daily.co/v1/rooms' \
  --header "Authorization: Bearer $DAILY_API_KEY" \
  --header 'Content-Type: application/json' \
  --data '{
    "name": "my-voice-room",
    "properties": {
      "enable_dialin": true
    }
  }'
```

Response includes dial-in info:
```json
{
  "name": "my-voice-room",
  "url": "https://your-domain.daily.co/my-voice-room",
  "dialin_info": {
    "phone_numbers": ["+1-555-xxx-xxxx", ...],
    "pin": "12345678901"
  }
}
```

---

## Automated Setup Script

The project includes a script that automates the entire setup process:

```bash
# Prerequisites:
# 1. Add DAILY_API_KEY to backend/voice-agent/.env
# 2. Deploy the BotRunner stack (provides webhook URL)

# Run the setup script
cd infrastructure/scripts
./setup-daily.sh

# Or specify a different region
PHONE_REGION=NY ./setup-daily.sh
```

The script will:
1. Load `DAILY_API_KEY` from `backend/voice-agent/.env`
2. Fetch the webhook URL from SSM (deployed infrastructure)
3. List available phone numbers in your region
4. Purchase the first available number (with confirmation)
5. Configure pinless dial-in with your webhook
6. Save `DAILY_PHONE_NUMBER` and `DAILY_HMAC_SECRET` to `.env`

After running, sync secrets to AWS:
```bash
./scripts/init-secrets.sh
```

---

## Troubleshooting

### Webhook returns 400
- Ensure your endpoint returns 200 within a few seconds
- Check that the URL is publicly accessible (not localhost)

### Call drops after connecting
- Make sure you wait for `dialin-ready` before calling `pinlessCallUpdate`
- Verify the `sipUri` is correct and not already in use

### No webhook received
- Verify `pinless_dialin` configuration with `GET /v1`
- Check that the phone number matches exactly (including +1)
- Ensure your webhook URL is HTTPS

---

## References

- [Daily REST API Overview](https://docs.daily.co/reference/rest-api)
- [Phone Numbers API](https://docs.daily.co/reference/rest-api/phone-numbers)
- [Pinless Dial-in Guide](https://docs.daily.co/guides/products/dial-in-dial-out/dialin-pinless)
- [Pipecat PSTN Guide](https://docs.pipecat.ai/guides/telephony/daily-pstn)
