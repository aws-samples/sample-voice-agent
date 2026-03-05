#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { loadConfig } from './config';
import {
  NetworkStack,
  StorageStack,
  SageMakerStack,
  SageMakerStubStack,
  KnowledgeBaseStack,
  EcsStack,
  BotRunnerStack,
  CrmStack,
  KbAgentStack,
  CrmAgentStack,
  AppointmentStack,
  AppointmentAgentStack,
  CallFlowVisualizerStack,
} from './stacks';

const app = new cdk.App();

// Load and validate configuration
const config = loadConfig(app);

// Environment configuration for all stacks
const env: cdk.Environment = {
  account: process.env.CDK_DEFAULT_ACCOUNT || process.env.AWS_ACCOUNT_ID,
  region: config.region,
};

/**
 * Stack instantiation with dependencies via SSM Parameters.
 *
 * SSM Parameters are used for cross-stack communication to:
 * - Avoid cyclic dependencies
 * - Allow independent stack deployments
 * - Support multi-account/region scenarios
 *
 * Deployment order (enforced by addDependency):
 *
 * 1. Network Stack (no dependencies)
 *    └── Writes: VPC ID, Subnet IDs, Security Group IDs
 *
 * 2. Storage Stack (depends on Network for VPC endpoints)
 *    └── Writes: Secret ARN, KMS Key ARN
 *
 * 3. SageMaker Stack (depends on Network) - OPTIONAL
 *    └── Reads: VPC ID, SageMaker SG ID
 *    └── Writes: STT/TTS Endpoint Names
 *    └── Skipped when USE_CLOUD_APIS=true
 *
 * 4. Knowledge Base Stack (no dependencies on other app stacks)
 *    └── Creates: KB, S3 bucket, data source
 *    └── Writes: KB ID, KB ARN, Bucket name to SSM
 *    └── Can be deployed independently for document updates
 *
 * 5. ECS Stack (depends on Network, Storage, Knowledge Base)
 *    └── Reads: VPC ID, Subnet IDs, Secret ARN, KB ID/ARN
 *    └── Writes: Cluster ARN, Task Definition ARN, Task SG ID
 *    └── Runs pipecat with asyncio.run() - the pattern pipecat expects
 *
 * 6. BotRunner Stack (depends on Network, Storage, SageMaker, ECS)
 *    └── Reads: VPC ID, Subnet IDs, Lambda SG ID, Secret ARN, ECS ARNs
 *    └── Writes: Webhook URL
 */

// Phase 2: Network Stack (no dependencies)
const networkStack = new NetworkStack(app, 'VoiceAgentNetwork', {
  env,
  config,
  description: 'Voice Agent POC - Network infrastructure (VPC, subnets, endpoints)',
  tags: {
    Project: config.projectName,
    Environment: config.environment,
    Phase: '2',
  },
});

// Phase 3: Storage Stack
const storageStack = new StorageStack(app, 'VoiceAgentStorage', {
  env,
  config,
  description: 'Voice Agent POC - Storage infrastructure (Secrets Manager)',
  tags: {
    Project: config.projectName,
    Environment: config.environment,
    Phase: '3',
  },
});
storageStack.addDependency(networkStack);

// Phase 4: SageMaker Stack (or Stub for cloud API mode)
// Use stub when USE_CLOUD_APIS=true to skip SageMaker deployment
const useCloudApis = process.env.USE_CLOUD_APIS === 'true';
const sagemakerStack = useCloudApis
  ? new SageMakerStubStack(app, 'VoiceAgentSageMaker', {
      env,
      config,
      description: 'Voice Agent POC - Cloud API mode (SageMaker skipped)',
      tags: {
        Project: config.projectName,
        Environment: config.environment,
        Phase: '4',
        Mode: 'cloud-api',
      },
    })
  : new SageMakerStack(app, 'VoiceAgentSageMaker', {
      env,
      config,
      description: 'Voice Agent POC - SageMaker endpoints (Deepgram STT/TTS)',
      tags: {
        Project: config.projectName,
        Environment: config.environment,
        Phase: '4',
      },
    });
sagemakerStack.addDependency(networkStack);

// Phase 5: Knowledge Base Stack (standalone for RAG)
// Deployed separately so document updates don't affect compute
const knowledgeBaseStack = new KnowledgeBaseStack(app, 'VoiceAgentKnowledgeBase', {
  env,
  config,
  description: 'Voice Agent POC - Bedrock Knowledge Base for RAG',
  tags: {
    Project: config.projectName,
    Environment: config.environment,
    Phase: '5',
  },
});

// Phase 6: ECS Stack
// ECS Fargate properly supports pipecat's async patterns
const ecsStack = new EcsStack(app, 'VoiceAgentEcs', {
  env,
  config,
  description: 'Voice Agent POC - ECS Fargate for Pipecat',
  tags: {
    Project: config.projectName,
    Environment: config.environment,
    Phase: '6',
  },
});
ecsStack.addDependency(networkStack);
ecsStack.addDependency(storageStack);
ecsStack.addDependency(knowledgeBaseStack);

// Phase 7: Bot Runner Stack
const botrunnerStack = new BotRunnerStack(app, 'VoiceAgentBotRunner', {
  env,
  config,
  description: 'Voice Agent POC - Bot Runner Lambda and API Gateway',
  tags: {
    Project: config.projectName,
    Environment: config.environment,
    Phase: '7',
  },
});
botrunnerStack.addDependency(networkStack);
botrunnerStack.addDependency(storageStack);
botrunnerStack.addDependency(sagemakerStack);
botrunnerStack.addDependency(ecsStack);

// Phase 8: CRM Stack (standalone - can be deployed independently)
// Provides customer data, cases, and interaction tracking for voice agent
const crmStack = new CrmStack(app, 'VoiceAgentCRM', {
  env,
  config,
  description: 'Voice Agent POC - Simple CRM System (DynamoDB + API Gateway)',
  tags: {
    Project: config.projectName,
    Environment: config.environment,
    Phase: '8',
  },
});

// Phase 9: KB Agent Stack (capability agent - depends on ECS + KB)
// Knowledge Base search as an independent A2A capability agent
const kbAgentStack = new KbAgentStack(app, 'VoiceAgentKbAgent', {
  env,
  config,
  description: 'Voice Agent POC - Knowledge Base A2A Capability Agent',
  tags: {
    Project: config.projectName,
    Environment: config.environment,
    Phase: '9',
  },
});
kbAgentStack.addDependency(ecsStack);
kbAgentStack.addDependency(knowledgeBaseStack);

// Phase 10: CRM Agent Stack (capability agent - depends on ECS + CRM)
// CRM operations as an independent A2A capability agent
const crmAgentStack = new CrmAgentStack(app, 'VoiceAgentCrmAgent', {
  env,
  config,
  description: 'Voice Agent POC - CRM A2A Capability Agent',
  tags: {
    Project: config.projectName,
    Environment: config.environment,
    Phase: '10',
  },
});
crmAgentStack.addDependency(ecsStack);
crmAgentStack.addDependency(crmStack);

// Phase 12: Appointment Stack (standalone - can be deployed independently)
// Provides appointment scheduling for the voice agent
const appointmentStack = new AppointmentStack(app, 'VoiceAgentAppointment', {
  env,
  config,
  description: 'Voice Agent POC - Appointment Scheduling (DynamoDB + API Gateway)',
  tags: {
    Project: config.projectName,
    Environment: config.environment,
    Phase: '12',
  },
});

// Phase 13: Appointment Agent Stack (capability agent - depends on ECS + Appointment)
// Appointment scheduling as an independent A2A capability agent
const appointmentAgentStack = new AppointmentAgentStack(app, 'VoiceAgentAppointmentAgent', {
  env,
  config,
  description: 'Voice Agent POC - Appointment Scheduling A2A Capability Agent',
  tags: {
    Project: config.projectName,
    Environment: config.environment,
    Phase: '13',
  },
});
appointmentAgentStack.addDependency(ecsStack);
appointmentAgentStack.addDependency(appointmentStack);

// Phase 11: Call Flow Visualizer (optional - bolt-on add-on)
// Enable with: -c voice-agent:enableCallFlowVisualizer=true
if (config.enableCallFlowVisualizer) {
  const visualizerStack = new CallFlowVisualizerStack(app, 'VoiceAgentCallFlowVisualizer', {
    env,
    config,
    description: 'Voice Agent - Call Flow Visualizer (optional)',
    tags: {
      Project: config.projectName,
      Environment: config.environment,
      Phase: '11',
    },
  });
  visualizerStack.addDependency(ecsStack);
}

app.synth();
