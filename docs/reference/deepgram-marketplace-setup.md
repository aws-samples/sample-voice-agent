# Deepgram Marketplace Setup Guide

This guide walks through subscribing to Deepgram model packages on AWS Marketplace, which is required for deploying the voice agent in **SageMaker mode**.

> **Note:** If you are using **Cloud API mode** (`USE_CLOUD_APIS=true`), you do not need Marketplace subscriptions. You only need a Deepgram API key from [console.deepgram.com](https://console.deepgram.com/).

## Overview

The voice agent uses two Deepgram models hosted on SageMaker:

| Model | Purpose | Instance Type | Streaming |
|-------|---------|---------------|-----------|
| **Deepgram Nova-3** | Speech-to-Text (STT) | ml.g6.2xlarge (1x L4 GPU) | BiDi HTTP/2 |
| **Deepgram Aura** | Text-to-Speech (TTS) | ml.g6.12xlarge (4x L4 GPU) | BiDi HTTP/2 |

## Step 1: Navigate to AWS Marketplace

1. Sign in to the [AWS Management Console](https://console.aws.amazon.com/)
2. Navigate to [AWS Marketplace Subscriptions](https://console.aws.amazon.com/marketplace/home#/subscriptions)
3. Click **Discover products**

## Step 2: Subscribe to Deepgram STT (Nova-3)

1. Search for **"Deepgram"** in the Marketplace search bar
2. Find the **Deepgram Streaming Speech-to-Text** listing (look for "Nova" or "streaming STT")
   - Publisher: Deepgram
   - Delivery method: Amazon SageMaker
3. Click **Continue to Subscribe**
4. Review the pricing and terms:
   - Pricing is per-instance-hour for the SageMaker endpoint
   - The endpoint runs continuously while deployed
5. Click **Accept Terms**
6. Wait for the subscription to activate (usually 1-2 minutes)
   - Status changes from "Pending" to "Active"

## Step 3: Subscribe to Deepgram TTS (Aura)

1. Return to **Discover products** and search for **"Deepgram"** again
2. Find the **Deepgram Streaming Text-to-Speech** listing (look for "Aura" or "streaming TTS")
   - Publisher: Deepgram
   - Delivery method: Amazon SageMaker
3. Click **Continue to Subscribe**
4. Review pricing and accept terms
5. Wait for activation

## Step 4: Find Your Model Package ARNs

After both subscriptions are active:

1. Go to [AWS Marketplace Subscriptions](https://console.aws.amazon.com/marketplace/home#/subscriptions)
2. Click on the **Deepgram STT** subscription
3. Click **Usage instructions** or **Launch new instance**
4. Look for the **Model Package ARN** -- it will look like:
   ```
   arn:aws:sagemaker:us-east-1:865070037744:model-package/deepgram-streaming-stt-...
   ```
5. Copy this ARN
6. Repeat for the **Deepgram TTS** subscription:
   ```
   arn:aws:sagemaker:us-east-1:865070037744:model-package/deepgram-streaming-tts-...
   ```

> **Important:** The ARN includes a region (e.g., `us-east-1`). Make sure you are viewing the subscription in the same region where you plan to deploy.

## Step 5: Configure Your Deployment

Add the ARNs to your infrastructure `.env` file:

```bash
cd infrastructure

# Edit .env
DEEPGRAM_STT_MODEL_PACKAGE_ARN=arn:aws:sagemaker:us-east-1:865070037744:model-package/deepgram-streaming-stt-...
DEEPGRAM_TTS_MODEL_PACKAGE_ARN=arn:aws:sagemaker:us-east-1:865070037744:model-package/deepgram-streaming-tts-...
```

Or pass them via CDK context:
```bash
npx cdk deploy --all \
  -c deepgram:sttModelPackageArn="arn:aws:sagemaker:us-east-1:865070037744:model-package/deepgram-streaming-stt-..." \
  -c deepgram:ttsModelPackageArn="arn:aws:sagemaker:us-east-1:865070037744:model-package/deepgram-streaming-tts-..."
```

## Step 6: Request SageMaker GPU Quotas

Before deploying, ensure you have sufficient GPU quota:

1. Go to [Service Quotas console](https://console.aws.amazon.com/servicequotas/)
2. Search for **"SageMaker"**
3. Request increases for:

| Quota Name | Required Value |
|------------|---------------|
| `ml.g6.2xlarge for endpoint usage` | 2+ |
| `ml.g6.12xlarge for endpoint usage` | 2+ |

> **Note:** GPU quota increases can take 24-48 hours. Request them before attempting deployment.

## References

- [AWS Marketplace Subscriptions](https://console.aws.amazon.com/marketplace/home#/subscriptions)
- [Deepgram on AWS Marketplace](https://aws.amazon.com/marketplace/seller-profile?id=deepgram)
- [SageMaker Model Packages](https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-marketplace.html)
