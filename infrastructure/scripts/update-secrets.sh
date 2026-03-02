#!/bin/bash
# Update API keys in AWS Secrets Manager
# Run this after deploying the infrastructure

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Updating API keys in Secrets Manager...${NC}"

# Get the secret ARN from SSM Parameter
SECRET_ARN=$(aws ssm get-parameter \
  --name /voice-agent/storage/api-key-secret-arn \
  --query 'Parameter.Value' \
  --output text 2>/dev/null)

if [ -z "$SECRET_ARN" ] || [ "$SECRET_ARN" == "None" ]; then
  echo -e "${RED}Error: Could not find secret ARN. Have you deployed the infrastructure?${NC}"
  echo "Run: USE_CLOUD_APIS=true npx cdk deploy --all"
  exit 1
fi

echo -e "Found secret: ${GREEN}$SECRET_ARN${NC}"

# Update the secret with API keys
# Replace placeholders with your actual API keys
aws secretsmanager put-secret-value \
  --secret-id "$SECRET_ARN" \
  --secret-string '{
    "DAILY_API_KEY": "your-daily-api-key-here",
    "DEEPGRAM_API_KEY": "your-deepgram-api-key-here",
    "CARTESIA_API_KEY": "your-cartesia-api-key-here"
  }'

echo -e "${GREEN}API keys updated successfully!${NC}"
echo ""
echo "Next steps:"
echo "1. Configure Daily webhook URL in your Daily dashboard"
echo "2. Test with: curl -X POST <api-gateway-url>/webhook -H 'Content-Type: application/json' -d '{\"type\":\"test\"}'"
