import * as cdk from 'aws-cdk-lib';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets';
import * as servicediscovery from 'aws-cdk-lib/aws-servicediscovery';
import * as path from 'path';
import { Construct } from 'constructs';
import { VoiceAgentConfig } from '../config';
import { SSM_PARAMS } from '../ssm-parameters';
import { CapabilityAgentConstruct } from '../constructs';

/**
 * Props for KbAgentStack
 */
export interface KbAgentStackProps extends cdk.StackProps {
  readonly config: VoiceAgentConfig;
}

/**
 * Knowledge Base Capability Agent stack.
 *
 * Deploys a Strands A2A agent that provides knowledge base search capabilities
 * as an independent ECS Fargate service. The agent:
 * - Registers in CloudMap for automatic discovery by the voice agent
 * - Exposes search_knowledge_base tool via A2A protocol
 * - Auto-generates Agent Card from @tool docstrings
 * - Queries Bedrock Knowledge Base for RAG retrieval
 *
 * This stack is deployable independently from the voice agent stack.
 */
export class KbAgentStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: KbAgentStackProps) {
    super(scope, id, props);

    const { config } = props;
    const resourcePrefix = `${config.projectName}-${config.environment}`;

    // Read cross-stack dependencies from SSM
    //
    // VPC_ID uses valueFromLookup (synth-time) because Vpc.fromLookup() needs
    // the actual VPC ID to resolve subnets/AZs via context queries. VPC IDs
    // are stable and rarely change, so synth-time resolution is safe here.
    //
    // All other parameters use valueForStringParameter (deploy-time) to avoid
    // stale values when the producing stack (e.g., EcsStack) replaces resources.
    // Deploy-time resolution uses CloudFormation dynamic references
    // ({{resolve:ssm:...}}) which always read the current SSM value.
    const vpcId = ssm.StringParameter.valueFromLookup(this, SSM_PARAMS.VPC_ID);

    const voiceAgentSgId = ssm.StringParameter.valueForStringParameter(
      this,
      SSM_PARAMS.ECS_TASK_SG_ID
    );
    const namespaceId = ssm.StringParameter.valueForStringParameter(
      this,
      SSM_PARAMS.A2A_NAMESPACE_ID
    );
    const namespaceName = ssm.StringParameter.valueForStringParameter(
      this,
      SSM_PARAMS.A2A_NAMESPACE_NAME
    );
    const kbId = ssm.StringParameter.valueForStringParameter(
      this,
      SSM_PARAMS.KNOWLEDGE_BASE_ID
    );
    const ecsClusterArn = ssm.StringParameter.valueForStringParameter(
      this,
      SSM_PARAMS.ECS_CLUSTER_ARN
    );

    // Import VPC
    const vpc = ec2.Vpc.fromLookup(this, 'ImportedVpc', { vpcId });

    // Import voice agent security group (for ingress rules)
    const voiceAgentSg = ec2.SecurityGroup.fromSecurityGroupId(
      this,
      'VoiceAgentSG',
      voiceAgentSgId
    );

    // Import CloudMap namespace
    const namespace = servicediscovery.HttpNamespace.fromHttpNamespaceAttributes(
      this,
      'ImportedNamespace',
      {
        namespaceId,
        namespaceName,
        namespaceArn: `arn:aws:servicediscovery:${this.region}:${this.account}:namespace/${namespaceId}`,
      }
    );

    // Import ECS cluster
    const cluster = ecs.Cluster.fromClusterAttributes(this, 'ImportedCluster', {
      clusterName: `${resourcePrefix}-cluster`,
      clusterArn: ecsClusterArn,
      vpc,
      securityGroups: [],
    });

    // Build the KB agent container image
    const containerImage = new ecr_assets.DockerImageAsset(this, 'KbAgentImage', {
      directory: path.join(__dirname, '..', '..', '..', 'backend', 'agents', 'knowledge-base-agent'),
      platform: ecr_assets.Platform.LINUX_AMD64,
    });

    // Create the capability agent using the reusable construct
    const kbAgent = new CapabilityAgentConstruct(this, 'KbAgent', {
      agentName: 'knowledge-base',
      environment: config.environment,
      projectName: config.projectName,
      cluster,
      vpc,
      namespace,
      voiceAgentSecurityGroup: voiceAgentSg,
      containerImage: ecs.ContainerImage.fromDockerImageAsset(containerImage),
      cpu: 256,
      memoryLimitMiB: 512,
      containerPort: 8000,
      enableBedrockAccess: true,
      environment_vars: {
        KB_KNOWLEDGE_BASE_ID: kbId,
        KB_RETRIEVAL_MAX_RESULTS: '3',
        KB_MIN_CONFIDENCE_SCORE: '0.3',
      },
      // Additional policy: Bedrock KB retrieval
      additionalPolicies: [
        new iam.PolicyStatement({
          sid: 'BedrockKBRetrieve',
          effect: iam.Effect.ALLOW,
          actions: [
            'bedrock:Retrieve',
            'bedrock:RetrieveAndGenerate',
          ],
          resources: [
            `arn:aws:bedrock:${this.region}:${this.account}:knowledge-base/*`,
          ],
        }),
      ],
    });

    // Grant ECR pull to execution role (the construct creates an execution role
    // but we need to grant pull from the specific image asset)
    containerImage.repository.grantPull(
      kbAgent.taskDefinition.executionRole!
    );
  }
}
