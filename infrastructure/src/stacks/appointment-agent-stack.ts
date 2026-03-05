import * as cdk from 'aws-cdk-lib';
import * as ecs from 'aws-cdk-lib/aws-ecs';
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
 * Props for AppointmentAgentStack
 */
export interface AppointmentAgentStackProps extends cdk.StackProps {
  readonly config: VoiceAgentConfig;
}

/**
 * Appointment Scheduling Capability Agent stack.
 *
 * Deploys a Strands A2A agent that provides appointment scheduling capabilities
 * as an independent ECS Fargate service. The agent:
 * - Registers in CloudMap for automatic discovery by the voice agent
 * - Exposes 5 appointment tools via A2A protocol:
 *   check_availability, book_appointment, get_appointment,
 *   cancel_appointment, reschedule_appointment
 * - Auto-generates Agent Card from @tool docstrings
 * - Communicates with the Appointment REST API (API Gateway + Lambda)
 *
 * This stack is deployable independently from the voice agent stack.
 */
export class AppointmentAgentStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: AppointmentAgentStackProps) {
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
    const appointmentApiUrl = ssm.StringParameter.valueForStringParameter(
      this,
      SSM_PARAMS.APPOINTMENT_API_URL
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

    // Build the Appointment agent container image
    const containerImage = new ecr_assets.DockerImageAsset(this, 'AppointmentAgentImage', {
      directory: path.join(__dirname, '..', '..', '..', 'backend', 'agents', 'appointment-agent'),
      platform: ecr_assets.Platform.LINUX_AMD64,
    });

    // Create the capability agent using the reusable construct
    // Appointment agent needs Bedrock model access (for Strands agent reasoning)
    // but does NOT need Bedrock KB permissions.
    // Appointment API access is via outbound HTTPS (API Gateway endpoint).
    const appointmentAgent = new CapabilityAgentConstruct(this, 'AppointmentAgent', {
      agentName: 'appointment',
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
        APPOINTMENT_API_URL: appointmentApiUrl,
      },
      // No additional IAM policies needed — Appointment API is accessed via HTTPS
      // and Bedrock model invocation is handled by enableBedrockAccess
    });

    // Grant ECR pull to execution role
    containerImage.repository.grantPull(
      appointmentAgent.taskDefinition.executionRole!
    );
  }
}
