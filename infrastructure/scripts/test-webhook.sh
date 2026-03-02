#!/bin/bash
# Test the webhook endpoint with a simulated Daily dial-in payload
# Usage: ./test-webhook.sh [webhook_url]

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Configuration
AWS_REGION=${AWS_REGION:-us-east-1}
PROJECT_NAME="voice-agent"

echo -e "${CYAN}======================================"
echo "Voice Agent Webhook Test"
echo -e "======================================${NC}"
echo ""

# Get webhook URL
if [ -n "$1" ]; then
    WEBHOOK_URL="$1"
else
    echo "Fetching webhook URL from SSM..."
    WEBHOOK_URL=$(aws ssm get-parameter --name "/${PROJECT_NAME}/botrunner/webhook-url" --region "$AWS_REGION" --query 'Parameter.Value' --output text 2>/dev/null)
fi

if [ -z "$WEBHOOK_URL" ] || [ "$WEBHOOK_URL" == "None" ]; then
    echo -e "${RED}Error: Webhook URL not found${NC}"
    echo "Usage: ./test-webhook.sh <webhook_url>"
    echo "  or set /${PROJECT_NAME}/botrunner/webhook-url SSM parameter"
    exit 1
fi

echo -e "Webhook URL: ${CYAN}$WEBHOOK_URL${NC}"
echo ""

# Generate test data
CALL_ID="test-$(date +%s)"
FROM_NUMBER="+15551234567"
TO_NUMBER="+15559876543"

# Test 1: Valid request
echo -e "${YELLOW}Test 1: Valid webhook payload${NC}"
echo "----------------------------"

PAYLOAD=$(cat <<EOF
{
  "callId": "$CALL_ID",
  "callDomain": "test.daily.co",
  "from": "$FROM_NUMBER",
  "to": "$TO_NUMBER",
  "direction": "inbound"
}
EOF
)

echo "Request:"
echo "$PAYLOAD" | jq .
echo ""

echo "Response:"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    --connect-timeout 30)

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
echo ""
echo -e "HTTP Status: ${HTTP_CODE}"

if [ "$HTTP_CODE" == "200" ]; then
    echo -e "${GREEN}✓ Test passed - Session started successfully${NC}"
elif [ "$HTTP_CODE" == "500" ]; then
    echo -e "${YELLOW}! Test returned 500 - Check Lambda logs for details${NC}"
    echo "  This may be expected if Daily/ECS credentials are not configured"
else
    echo -e "${RED}✗ Test failed - Unexpected HTTP status${NC}"
fi

echo ""

# Test 2: Missing callId
echo -e "${YELLOW}Test 2: Missing callId (should return 400)${NC}"
echo "-------------------------------------------"

PAYLOAD='{"callDomain": "test.daily.co", "from": "+15551234567"}'

echo "Request:"
echo "$PAYLOAD" | jq .
echo ""

echo "Response:"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    --connect-timeout 10)

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
echo ""
echo -e "HTTP Status: ${HTTP_CODE}"

if [ "$HTTP_CODE" == "400" ]; then
    echo -e "${GREEN}✓ Test passed - Correctly returned 400 for missing callId${NC}"
else
    echo -e "${RED}✗ Test failed - Expected 400, got $HTTP_CODE${NC}"
fi

echo ""

# Test 3: Missing callDomain
echo -e "${YELLOW}Test 3: Missing callDomain (should return 400)${NC}"
echo "----------------------------------------------"

PAYLOAD='{"callId": "test-123", "from": "+15551234567"}'

echo "Request:"
echo "$PAYLOAD" | jq .
echo ""

echo "Response:"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    --connect-timeout 10)

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
echo ""
echo -e "HTTP Status: ${HTTP_CODE}"

if [ "$HTTP_CODE" == "400" ]; then
    echo -e "${GREEN}✓ Test passed - Correctly returned 400 for missing callDomain${NC}"
else
    echo -e "${RED}✗ Test failed - Expected 400, got $HTTP_CODE${NC}"
fi

echo ""

# Test 4: Invalid JSON
echo -e "${YELLOW}Test 4: Invalid JSON (should return 400)${NC}"
echo "-----------------------------------------"

PAYLOAD='not valid json {'

echo "Request: $PAYLOAD"
echo ""

echo "Response:"
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    --connect-timeout 10)

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
echo ""
echo -e "HTTP Status: ${HTTP_CODE}"

if [ "$HTTP_CODE" == "400" ]; then
    echo -e "${GREEN}✓ Test passed - Correctly returned 400 for invalid JSON${NC}"
else
    echo -e "${RED}✗ Test failed - Expected 400, got $HTTP_CODE${NC}"
fi

echo ""
echo -e "${CYAN}======================================"
echo "Tests Complete"
echo -e "======================================${NC}"
