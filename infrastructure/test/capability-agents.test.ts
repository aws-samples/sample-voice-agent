import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as servicediscovery from 'aws-cdk-lib/aws-servicediscovery';
import { KbAgentStack } from '../src/stacks/kb-agent-stack';
import { CrmAgentStack } from '../src/stacks/crm-agent-stack';
import { NetworkStack } from '../src/stacks/network-stack';
import { StorageStack } from '../src/stacks/storage-stack';
import { EcsStack } from '../src/stacks/ecs-stack';
import { CrmStack } from '../src/stacks/crm-stack';
import { KnowledgeBaseStack } from '../src/stacks/knowledge-base-stack';
import { KnowledgeBaseConstruct, CapabilityAgentConstruct } from '../src/constructs';
import { SSM_PARAMS } from '../src/ssm-parameters';
import {
  TEST_CONFIG,
  TEST_ENV,
  AGENT_SSM_CONTEXT,
  ECS_SSM_CONTEXT,
  DEPENDENCY_SSM_CONTEXT,
} from './helpers';

describe('KnowledgeBaseConstruct', () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new cdk.Stack(app, 'TestKBStack', { env: TEST_ENV });

    new KnowledgeBaseConstruct(stack, 'TestKnowledgeBase', {
      environment: 'poc',
      projectName: 'test-voice-agent',
      region: 'us-east-1',
      account: '123456789012',
    });

    template = Template.fromStack(stack);
  });

  it('should create S3 bucket for documents', () => {
    template.resourceCountIs('AWS::S3::Bucket', 1);
  });

  it('should create S3 bucket with encryption', () => {
    template.hasResourceProperties('AWS::S3::Bucket', {
      BucketEncryption: {
        ServerSideEncryptionConfiguration: Match.arrayWith([
          Match.objectLike({
            ServerSideEncryptionByDefault: {
              SSEAlgorithm: 'AES256',
            },
          }),
        ]),
      },
    });
  });

  it('should create IAM role for Bedrock Knowledge Base', () => {
    template.hasResourceProperties('AWS::IAM::Role', {
      AssumeRolePolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: 'sts:AssumeRole',
            Effect: 'Allow',
            Principal: {
              Service: 'bedrock.amazonaws.com',
            },
          }),
        ]),
      },
    });
  });

  it('should grant S3 access to Bedrock role', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: Match.arrayWith(['s3:GetObject', 's3:ListBucket']),
            Effect: 'Allow',
          }),
        ]),
      },
    });
  });

  it('should grant S3 Vectors access to Bedrock role', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: Match.arrayWith([
              's3vectors:CreateIndex',
              's3vectors:PutVectors',
              's3vectors:QueryVectors',
            ]),
            Effect: 'Allow',
          }),
        ]),
      },
    });
  });

  it('should create Lambda function for KB management', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      Runtime: 'python3.12',
      Handler: 'index.handler',
      Timeout: 600,
    });
  });

  it('should grant Lambda S3 Vectors management permissions', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: Match.arrayWith([
              's3vectors:CreateVectorBucket',
              's3vectors:DeleteVectorBucket',
              's3vectors:CreateIndex',
              's3vectors:DeleteIndex',
            ]),
            Effect: 'Allow',
          }),
        ]),
      },
    });
  });

  it('should grant Lambda Bedrock KB management permissions', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: Match.arrayWith([
              'bedrock:CreateKnowledgeBase',
              'bedrock:DeleteKnowledgeBase',
              'bedrock:CreateDataSource',
              'bedrock:StartIngestionJob',
            ]),
            Effect: 'Allow',
          }),
        ]),
      },
    });
  });

  it('should create Custom Resource for KB lifecycle', () => {
    template.resourceCountIs('AWS::CloudFormation::CustomResource', 1);
  });

  it('should create SSM parameter for Knowledge Base ID', () => {
    template.hasResourceProperties('AWS::SSM::Parameter', {
      Name: SSM_PARAMS.KNOWLEDGE_BASE_ID,
    });
  });

  it('should create SSM parameter for Knowledge Base ARN', () => {
    template.hasResourceProperties('AWS::SSM::Parameter', {
      Name: SSM_PARAMS.KNOWLEDGE_BASE_ARN,
    });
  });

  it('should create SSM parameter for document bucket', () => {
    template.hasResourceProperties('AWS::SSM::Parameter', {
      Name: SSM_PARAMS.KNOWLEDGE_BASE_BUCKET,
    });
  });

  it('should create outputs for Knowledge Base resources', () => {
    template.hasResourceProperties('AWS::CloudFormation::CustomResource', {
      VectorBucketName: Match.anyValue(),
      KnowledgeBaseName: Match.anyValue(),
      DocumentBucketArn: Match.anyValue(),
      BedrockRoleArn: Match.anyValue(),
      EmbeddingModelArn: Match.anyValue(),
    });
  });
});

describe('CapabilityAgentConstruct', () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new cdk.Stack(app, 'TestCapabilityAgentStack', { env: TEST_ENV });

    const vpc = new ec2.Vpc(stack, 'TestVpc', { maxAzs: 2 });
    const cluster = new ecs.Cluster(stack, 'TestCluster', { vpc });
    const namespace = new servicediscovery.HttpNamespace(stack, 'TestNamespace', {
      name: 'test-capabilities',
    });
    const voiceAgentSg = new ec2.SecurityGroup(stack, 'VoiceAgentSG', {
      vpc,
      description: 'Voice agent SG',
    });

    new CapabilityAgentConstruct(stack, 'TestAgent', {
      agentName: 'test-kb',
      environment: 'poc',
      projectName: 'test-voice-agent',
      cluster,
      vpc,
      namespace,
      voiceAgentSecurityGroup: voiceAgentSg,
      containerImage: ecs.ContainerImage.fromRegistry('public.ecr.aws/test/image:latest'),
    });

    template = Template.fromStack(stack);
  });

  it('should create a Fargate task definition', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      RequiresCompatibilities: ['FARGATE'],
      Cpu: '256',
      Memory: '512',
    });
  });

  it('should create an ECS Fargate service', () => {
    template.hasResourceProperties('AWS::ECS::Service', {
      LaunchType: 'FARGATE',
      ServiceRegistries: Match.anyValue(),
    });
  });

  it('should create a security group for the agent', () => {
    template.hasResourceProperties('AWS::EC2::SecurityGroup', {
      GroupDescription: Match.stringLikeRegexp('test-kb capability agent'),
    });
  });

  it('should allow inbound from voice agent security group', () => {
    template.hasResourceProperties('AWS::EC2::SecurityGroupIngress', {
      IpProtocol: 'tcp',
      FromPort: 8000,
      ToPort: 8000,
    });
  });

  it('should create CloudWatch log group', () => {
    template.hasResourceProperties('AWS::Logs::LogGroup', {
      LogGroupName: Match.stringLikeRegexp('test-kb-agent'),
      RetentionInDays: 14,
    });
  });

  it('should create task role with Bedrock permissions', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: Match.arrayWith([
              'bedrock:InvokeModel',
              'bedrock:InvokeModelWithResponseStream',
            ]),
            Effect: 'Allow',
          }),
        ]),
      },
    });
  });

  it('should set agent environment variables', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({
          Environment: Match.arrayWith([
            Match.objectLike({ Name: 'AGENT_NAME', Value: 'test-kb' }),
            Match.objectLike({ Name: 'PORT', Value: '8000' }),
          ]),
        }),
      ]),
    });
  });

  it('should configure health check', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({
          HealthCheck: {
            Command: ['CMD-SHELL', 'curl -f http://localhost:8000/.well-known/agent-card.json || exit 1'],
            Interval: 30,
            Timeout: 5,
            Retries: 3,
            StartPeriod: 60,
          },
        }),
      ]),
    });
  });

  it('should register with CloudMap namespace', () => {
    template.hasResourceProperties('AWS::ServiceDiscovery::Service', {
      Name: 'test-kb',
    });
  });

  it('should create execution role with ECS managed policy', () => {
    template.hasResourceProperties('AWS::IAM::Role', {
      ManagedPolicyArns: Match.arrayWith([
        Match.objectLike({
          'Fn::Join': Match.arrayWith([
            Match.arrayWith([
              Match.stringLikeRegexp('AmazonECSTaskExecutionRolePolicy'),
            ]),
          ]),
        }),
      ]),
    });
  });
});

describe('CapabilityAgentConstruct without Bedrock', () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new cdk.Stack(app, 'TestCapAgentNoBedrock', { env: TEST_ENV });

    const vpc = new ec2.Vpc(stack, 'TestVpc', { maxAzs: 2 });
    const cluster = new ecs.Cluster(stack, 'TestCluster', { vpc });
    const namespace = new servicediscovery.HttpNamespace(stack, 'TestNS', {
      name: 'test-caps',
    });
    const voiceAgentSg = new ec2.SecurityGroup(stack, 'VoiceAgentSG', {
      vpc,
      description: 'Voice agent SG',
    });

    new CapabilityAgentConstruct(stack, 'NoBrAgent', {
      agentName: 'no-bedrock',
      environment: 'poc',
      projectName: 'test-voice-agent',
      cluster,
      vpc,
      namespace,
      voiceAgentSecurityGroup: voiceAgentSg,
      containerImage: ecs.ContainerImage.fromRegistry('public.ecr.aws/test/image:latest'),
      enableBedrockAccess: false,
      cpu: 512,
      memoryLimitMiB: 1024,
      containerPort: 9000,
    });

    template = Template.fromStack(stack);
  });

  it('should use custom CPU and memory', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      Cpu: '512',
      Memory: '1024',
    });
  });

  it('should use custom container port', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({
          PortMappings: Match.arrayWith([
            Match.objectLike({ ContainerPort: 9000 }),
          ]),
        }),
      ]),
    });
  });

  it('should not include Bedrock permissions when disabled', () => {
    const policies = template.findResources('AWS::IAM::Policy');
    const hasBedrock = Object.values(policies).some((policy: any) => {
      const statements = policy.Properties?.PolicyDocument?.Statement || [];
      return statements.some((s: any) => {
        const actions = Array.isArray(s.Action) ? s.Action : [s.Action];
        return actions.some((a: string) => a.startsWith('bedrock:'));
      });
    });
    expect(hasBedrock).toBe(false);
  });
});

describe('KbAgentStack', () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App({ context: AGENT_SSM_CONTEXT });
    const stack = new KbAgentStack(app, 'TestKbAgentStack', {
      env: TEST_ENV,
      config: TEST_CONFIG,
    });
    template = Template.fromStack(stack);
  });

  it('should create a Fargate task definition via CapabilityAgentConstruct', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      Cpu: '256',
      Memory: '512',
      RequiresCompatibilities: ['FARGATE'],
    });
  });

  it('should create an ECS Fargate service', () => {
    template.hasResourceProperties('AWS::ECS::Service', {
      LaunchType: 'FARGATE',
    });
  });

  it('should set KB environment variables on container', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({
          Environment: Match.arrayWith([
            Match.objectLike({ Name: 'KB_KNOWLEDGE_BASE_ID' }),
            Match.objectLike({ Name: 'KB_RETRIEVAL_MAX_RESULTS', Value: '3' }),
            Match.objectLike({ Name: 'KB_MIN_CONFIDENCE_SCORE', Value: '0.3' }),
          ]),
        }),
      ]),
    });
  });

  it('should grant Bedrock KB retrieval permissions', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: Match.arrayWith([
              'bedrock:Retrieve',
              'bedrock:RetrieveAndGenerate',
            ]),
            Effect: 'Allow',
          }),
        ]),
      },
    });
  });

  it('should grant Bedrock model invocation permissions', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: Match.arrayWith([
              'bedrock:InvokeModel',
              'bedrock:InvokeModelWithResponseStream',
            ]),
            Effect: 'Allow',
          }),
        ]),
      },
    });
  });

  it('should create CloudMap service for discovery', () => {
    template.hasResourceProperties('AWS::ServiceDiscovery::Service', {
      Name: 'knowledge-base',
    });
  });

  it('should create security group allowing voice agent inbound', () => {
    template.hasResourceProperties('AWS::EC2::SecurityGroupIngress', {
      IpProtocol: 'tcp',
      FromPort: 8000,
      ToPort: 8000,
    });
  });

  it('should create CloudWatch log group', () => {
    template.hasResourceProperties('AWS::Logs::LogGroup', {
      LogGroupName: Match.stringLikeRegexp('knowledge-base-agent'),
      RetentionInDays: 14,
    });
  });

  it('should output the agent service name', () => {
    template.hasOutput('knowledgebaseAgentServiceName', {});
  });
});

describe('CrmAgentStack', () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App({ context: AGENT_SSM_CONTEXT });
    const stack = new CrmAgentStack(app, 'TestCrmAgentStack', {
      env: TEST_ENV,
      config: TEST_CONFIG,
    });
    template = Template.fromStack(stack);
  });

  it('should create a Fargate task definition via CapabilityAgentConstruct', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      Cpu: '256',
      Memory: '512',
      RequiresCompatibilities: ['FARGATE'],
    });
  });

  it('should create an ECS Fargate service', () => {
    template.hasResourceProperties('AWS::ECS::Service', {
      LaunchType: 'FARGATE',
    });
  });

  it('should set CRM_API_URL environment variable on container', () => {
    template.hasResourceProperties('AWS::ECS::TaskDefinition', {
      ContainerDefinitions: Match.arrayWith([
        Match.objectLike({
          Environment: Match.arrayWith([
            Match.objectLike({ Name: 'CRM_API_URL' }),
          ]),
        }),
      ]),
    });
  });

  it('should grant Bedrock model invocation permissions', () => {
    template.hasResourceProperties('AWS::IAM::Policy', {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: Match.arrayWith([
              'bedrock:InvokeModel',
              'bedrock:InvokeModelWithResponseStream',
            ]),
            Effect: 'Allow',
          }),
        ]),
      },
    });
  });

  it('should NOT grant Bedrock KB retrieval permissions', () => {
    const policies = template.findResources('AWS::IAM::Policy');
    for (const [, policy] of Object.entries(policies)) {
      const statements = (policy.Properties?.PolicyDocument?.Statement || []) as Array<{
        Action?: string[];
      }>;
      for (const stmt of statements) {
        if (Array.isArray(stmt.Action)) {
          expect(stmt.Action).not.toContain('bedrock:Retrieve');
          expect(stmt.Action).not.toContain('bedrock:RetrieveAndGenerate');
        }
      }
    }
  });

  it('should create CloudMap service for discovery', () => {
    template.hasResourceProperties('AWS::ServiceDiscovery::Service', {
      Name: 'crm',
    });
  });

  it('should create security group allowing voice agent inbound', () => {
    template.hasResourceProperties('AWS::EC2::SecurityGroupIngress', {
      IpProtocol: 'tcp',
      FromPort: 8000,
      ToPort: 8000,
    });
  });

  it('should create CloudWatch log group', () => {
    template.hasResourceProperties('AWS::Logs::LogGroup', {
      LogGroupName: Match.stringLikeRegexp('crm-agent'),
      RetentionInDays: 14,
    });
  });

  it('should output the agent service name', () => {
    template.hasOutput('crmAgentServiceName', {});
  });
});

describe('Stack Dependencies (Complete Graph)', () => {
  it('should correctly wire all stack dependencies', () => {
    const app = new cdk.App({ context: DEPENDENCY_SSM_CONTEXT });

    const networkStack = new NetworkStack(app, 'DepNetwork', { env: TEST_ENV, config: TEST_CONFIG });
    const storageStack = new StorageStack(app, 'DepStorage', { env: TEST_ENV, config: TEST_CONFIG });
    storageStack.addDependency(networkStack);

    const sagemakerStack = new cdk.Stack(app, 'DepSageMaker'); // stub
    sagemakerStack.addDependency(networkStack);

    const knowledgeBaseStack = new KnowledgeBaseStack(app, 'DepKB', { env: TEST_ENV, config: TEST_CONFIG });

    const ecsStack = new EcsStack(app, 'DepEcs', { env: TEST_ENV, config: TEST_CONFIG });
    ecsStack.addDependency(networkStack);
    ecsStack.addDependency(storageStack);
    ecsStack.addDependency(knowledgeBaseStack);

    const crmStack = new CrmStack(app, 'DepCRM', { env: TEST_ENV, config: TEST_CONFIG });

    const botrunnerStack = new cdk.Stack(app, 'DepBotRunner'); // stub
    botrunnerStack.addDependency(networkStack);
    botrunnerStack.addDependency(storageStack);
    botrunnerStack.addDependency(sagemakerStack);
    botrunnerStack.addDependency(ecsStack);

    const kbAgentStack = new KbAgentStack(app, 'DepKbAgent', { env: TEST_ENV, config: TEST_CONFIG });
    kbAgentStack.addDependency(ecsStack);
    kbAgentStack.addDependency(knowledgeBaseStack);

    const crmAgentStack = new CrmAgentStack(app, 'DepCrmAgent', { env: TEST_ENV, config: TEST_CONFIG });
    crmAgentStack.addDependency(ecsStack);
    crmAgentStack.addDependency(crmStack);

    // Original dependencies
    expect(storageStack.dependencies).toContain(networkStack);
    expect(sagemakerStack.dependencies).toContain(networkStack);
    expect(ecsStack.dependencies).toContain(networkStack);
    expect(ecsStack.dependencies).toContain(storageStack);
    expect(botrunnerStack.dependencies).toContain(networkStack);
    expect(botrunnerStack.dependencies).toContain(storageStack);
    expect(botrunnerStack.dependencies).toContain(sagemakerStack);
    expect(botrunnerStack.dependencies).toContain(ecsStack);

    // New: ECS depends on KB stack
    expect(ecsStack.dependencies).toContain(knowledgeBaseStack);

    // New: KB agent depends on ECS + KB
    expect(kbAgentStack.dependencies).toContain(ecsStack);
    expect(kbAgentStack.dependencies).toContain(knowledgeBaseStack);

    // New: CRM agent depends on ECS + CRM
    expect(crmAgentStack.dependencies).toContain(ecsStack);
    expect(crmAgentStack.dependencies).toContain(crmStack);
  });
});
