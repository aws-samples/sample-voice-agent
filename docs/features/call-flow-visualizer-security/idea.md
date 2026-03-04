---
id: call-flow-visualizer-security
name: Call Flow Visualizer Security Hardening
type: Enhancement
priority: P1
effort: Medium
impact: High
created: 2026-03-04
---

# Call Flow Visualizer Security Hardening

## Problem Statement

The Call Flow Visualizer shipped as an internal POC tool with four
security gaps identified during the shipping review. These are
acceptable for a single-developer environment behind VPN/Isengard but
must be resolved before the tool is accessible to any broader audience
(team members, stakeholders, or production use).

The four gaps, in priority order:

### 1. No API Authentication

**File:** `call-flow-visualizer-stack.ts:258-270`

All four API endpoints are unauthenticated. Anyone who discovers the
API Gateway URL or CloudFront domain can enumerate all call data.
There is no API key, IAM authorizer, Cognito authorizer, or Lambda
authorizer on any method.

### 2. CORS Allows All Origins

**Files:** `call-flow-visualizer-stack.ts:237`, `call-flow-api/handler.py:53`

CORS is configured with `Cors.ALL_ORIGINS` at the API Gateway level
and the Lambda hardcodes `Access-Control-Allow-Origin: *`. Any website
can make cross-origin requests to the API. Combined with the lack of
auth, any page on the internet can exfiltrate call data.

### 3. Unsafe Pagination Token Deserialization

**File:** `call-flow-api/handler.py:109`

```python
query_kwargs["ExclusiveStartKey"] = json.loads(next_token)
```

The `next_token` query parameter is client-supplied and deserialized
directly into a DynamoDB `ExclusiveStartKey` with no validation. An
attacker can craft tokens to scan from arbitrary partitions or cause
DynamoDB validation errors.

### 4. PII Exposure via Conversation Transcripts

**File:** `call-flow-ingester/handler.py:117-124`

When `ENABLE_CONVERSATION_LOGGING=true`, `conversation_turn` events
contain verbatim caller speech (`content` field) which may include
PII (names, account numbers, SSNs). This content is stored in
DynamoDB and served through the unauthenticated API.

## Proposed Fixes

### Fix 1: API Authentication with CloudFront Signed Cookies or IAM

Two options to evaluate:

**Option A: CloudFront signed cookies (recommended for browser access)**

- Generate a CloudFront key pair
- Add a lightweight auth Lambda@Edge or CloudFront Function on the
  default behavior that validates an IAM session or shared secret and
  sets signed cookies
- Both SPA and `/api/*` requests carry the cookie automatically
- No changes to API Gateway auth -- CloudFront blocks unauthenticated
  requests before they reach the API

**Option B: API Gateway IAM authorizer**

- Add `authorizationType: apigateway.AuthorizationType.IAM` to all
  methods
- Frontend uses SigV4 signing (requires AWS credentials in the
  browser, typically via Cognito Identity Pool)
- More complex frontend integration but stronger per-request auth

### Fix 2: Restrict CORS to CloudFront Domain

- CDK: Pass `distribution.distributionDomainName` as a Lambda
  environment variable (e.g., `ALLOWED_ORIGIN`)
- Lambda: Replace `Access-Control-Allow-Origin: *` with
  `Access-Control-Allow-Origin: https://{ALLOWED_ORIGIN}`
- API Gateway: Replace `Cors.ALL_ORIGINS` with the specific
  CloudFront URL
- This is a one-line fix in each location

### Fix 3: Sign Pagination Tokens

- Server-side: Encode the `ExclusiveStartKey` as JSON, then
  base64-encode and HMAC-sign it with a secret (e.g., from
  Secrets Manager or a Lambda environment variable derived from
  the stack)
- Return the signed token as `next_token` in list responses
- On receipt: verify the HMAC, reject tampered tokens with 400
- Library option: Python `itsdangerous` (URLSafeSerializer) handles
  signing + expiry in one call

### Fix 4: PII Handling for Conversation Content

Options to evaluate:

**Option A: Redact before storage (recommended)**

- In the ingester Lambda, strip the `content` field from
  `conversation_turn` events before writing to DynamoDB
- Store only metadata: speaker, turn number, timestamp, word count
- Timeline shows "Caller spoke (12 words)" instead of transcript
- Transcript remains available in CloudWatch Logs for users with
  log access

**Option B: Field-level encryption**

- Encrypt `content` with a KMS key before storage
- Decrypt in the query Lambda only for authorized requests
- Preserves transcript in the UI but adds latency and KMS cost

**Option C: Separate retention policy**

- Store `conversation_turn` events with a shorter TTL (e.g., 7 days
  instead of 30)
- Does not prevent exposure during the retention window

## Additional Hardening (from WARN items)

These are not blocking but should be addressed in the same pass:

| Item | Fix | Effort |
|------|-----|--------|
| No API throttling | Add `deployOptions.throttlingRateLimit: 50, throttlingBurstLimit: 100` to API Gateway | Trivial |
| `call_id` not validated | Add UUID regex validation in query Lambda before DynamoDB query | Trivial |
| `limit` param no error handling | Wrap `int()` in try/except, return 400 for non-integer | Trivial |
| No security response headers | Add `ResponseHeadersPolicy` to CloudFront with CSP, HSTS, X-Frame-Options | Small |
| Unpinned Docker build image | Pin `node:20-slim` to a specific digest | Trivial |

## Scope

### In Scope

- API authentication (one of the two options above)
- CORS restriction to CloudFront domain
- Pagination token signing
- PII redaction or handling for conversation content
- API throttling
- Input validation (`call_id` format, `limit` type)
- CloudFront security response headers

### Out of Scope

- Cognito User Pool with login UI (separate feature if needed)
- DynamoDB encryption with CMK (low risk for non-PII after Fix 4)
- WAF WebACL (separate cost/complexity decision)
- Geographic restrictions

## Affected Areas

### Modified

| File | Changes |
|------|---------|
| `infrastructure/src/stacks/call-flow-visualizer-stack.ts` | Auth config, CORS origin, throttling, response headers, `ALLOWED_ORIGIN` env var |
| `infrastructure/src/functions/call-flow-api/handler.py` | CORS header, token validation, `call_id` validation, `limit` error handling |
| `infrastructure/src/functions/call-flow-ingester/handler.py` | PII redaction for `conversation_turn` content |
| `infrastructure/test/call-flow-visualizer.test.ts` | Tests for auth, throttling, new env vars |

### Possibly New

| File | Purpose |
|------|---------|
| `infrastructure/src/functions/call-flow-api/token_signer.py` | Pagination token signing/verification utility |
