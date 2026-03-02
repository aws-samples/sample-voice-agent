import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as servicediscovery from 'aws-cdk-lib/aws-servicediscovery';
import { Construct } from 'constructs';

/**
 * Props for CapabilityAgentConstruct
 */
export interface CapabilityAgentConstructProps {
  /**
   * Name of the capability agent (e.g., 'knowledge-base', 'crm').
   * Used for resource naming and CloudMap service registration.
   */
  readonly agentName: string;

  /**
   * Environment name (e.g., 'poc', 'dev', 'staging', 'prod')
   */
  readonly environment: string;

  /**
   * Project name prefix for resources
   */
  readonly projectName: string;

  /**
   * ECS cluster to deploy the agent into
   */
  readonly cluster: ecs.ICluster;

  /**
   * VPC for the agent's Fargate tasks
   */
  readonly vpc: ec2.IVpc;

  /**
   * CloudMap HTTP namespace for service registration.
   * The agent registers itself here so the voice agent can discover it.
   * Accepts both concrete HttpNamespace and imported IHttpNamespace references.
   */
  readonly namespace: servicediscovery.IHttpNamespace;

  /**
   * Security group of the voice agent ECS tasks.
   * Used to allow inbound traffic from the voice agent to this capability agent.
   */
  readonly voiceAgentSecurityGroup: ec2.ISecurityGroup;

  /**
   * Docker image for the capability agent container.
   * Can be an ECR asset, ECR repository image, or registry image.
   */
  readonly containerImage: ecs.ContainerImage;

  /**
   * CPU units for the Fargate task (default: 256 = 0.25 vCPU)
   */
  readonly cpu?: number;

  /**
   * Memory in MiB for the Fargate task (default: 512 MB)
   */
  readonly memoryLimitMiB?: number;

  /**
   * Desired number of running tasks (default: 1)
   */
  readonly desiredCount?: number;

  /**
   * Container port the agent listens on (default: 8000)
   */
  readonly containerPort?: number;

  /**
   * Health check path (default: '/.well-known/agent-card.json').
   * Strands A2AServer does not expose a /health route; the Agent Card
   * endpoint is always available and validates A2A protocol readiness.
   */
  readonly healthCheckPath?: string;

  /**
   * Additional environment variables for the container
   */
  readonly environment_vars?: Record<string, string>;

  /**
   * Whether the agent needs Bedrock model invocation permissions (default: true)
   */
  readonly enableBedrockAccess?: boolean;

  /**
   * Additional IAM policy statements for the task role
   */
  readonly additionalPolicies?: iam.PolicyStatement[];
}

/**
 * Reusable construct for deploying a capability agent as an ECS Fargate service.
 *
 * Creates:
 * - ECS Fargate task definition + service
 * - CloudMap service registration (HTTP namespace)
 * - CloudWatch log group
 * - IAM task role with optional Bedrock access
 * - Security group allowing inbound from voice agent
 *
 * The agent is discoverable by the voice agent's A2A registry via CloudMap
 * DiscoverInstances. It exposes an A2A-compatible HTTP endpoint that the
 * voice agent calls during tool execution.
 */
export class CapabilityAgentConstruct extends Construct {
  /** The ECS Fargate service running the agent */
  public readonly service: ecs.FargateService;

  /** The Fargate task definition */
  public readonly taskDefinition: ecs.FargateTaskDefinition;

  /** Security group for the agent's ECS tasks */
  public readonly securityGroup: ec2.SecurityGroup;

  /** The IAM task role (for granting additional permissions) */
  public readonly taskRole: iam.Role;

  /** CloudMap service for discovery */
  public readonly cloudMapService: servicediscovery.IService;

  constructor(scope: Construct, id: string, props: CapabilityAgentConstructProps) {
    super(scope, id);

    const {
      agentName,
      environment,
      projectName,
      cluster,
      vpc,
      namespace,
      voiceAgentSecurityGroup,
      containerImage,
      cpu = 256,
      memoryLimitMiB = 512,
      desiredCount = 1,
      containerPort = 8000,
      healthCheckPath = '/.well-known/agent-card.json',
      environment_vars = {},
      enableBedrockAccess = true,
      additionalPolicies = [],
    } = props;

    const resourcePrefix = `${projectName}-${environment}`;

    // =====================
    // Security Group
    // =====================
    this.securityGroup = new ec2.SecurityGroup(this, 'SecurityGroup', {
      vpc,
      description: `Security group for ${agentName} capability agent - ${resourcePrefix}`,
      allowAllOutbound: true, // Required for Bedrock API calls
    });

    // Allow inbound from voice agent ECS tasks
    this.securityGroup.addIngressRule(
      voiceAgentSecurityGroup,
      ec2.Port.tcp(containerPort),
      `Allow HTTP from voice agent to ${agentName} capability agent`
    );

    // =====================
    // CloudWatch Log Group
    // =====================
    const logGroup = new logs.LogGroup(this, 'LogGroup', {
      logGroupName: `/ecs/${resourcePrefix}-${agentName}-agent`,
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // =====================
    // IAM Task Role
    // =====================
    this.taskRole = new iam.Role(this, 'TaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      description: `Task role for ${agentName} capability agent - ${resourcePrefix}`,
    });

    if (enableBedrockAccess) {
      this.taskRole.addToPolicy(
        new iam.PolicyStatement({
          sid: 'BedrockInvokeModel',
          effect: iam.Effect.ALLOW,
          actions: [
            'bedrock:InvokeModel',
            'bedrock:InvokeModelWithResponseStream',
            'bedrock:Converse',
            'bedrock:ConverseStream',
          ],
          resources: [
            // Foundation models - allow all US regions for cross-region inference
            'arn:aws:bedrock:us-*::foundation-model/anthropic.claude-*',
            // Inference profiles
            `arn:aws:bedrock:${cdk.Stack.of(this).region}:${cdk.Stack.of(this).account}:inference-profile/us.anthropic.claude-*`,
          ],
        })
      );
    }

    // Apply additional policies
    for (const policy of additionalPolicies) {
      this.taskRole.addToPolicy(policy);
    }

    // =====================
    // Task Execution Role
    // =====================
    const executionRole = new iam.Role(this, 'ExecutionRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          'service-role/AmazonECSTaskExecutionRolePolicy'
        ),
      ],
    });

    // =====================
    // Task Definition
    // =====================
    this.taskDefinition = new ecs.FargateTaskDefinition(this, 'TaskDefinition', {
      family: `${resourcePrefix}-${agentName}-agent`,
      cpu,
      memoryLimitMiB,
      executionRole,
      taskRole: this.taskRole,
      runtimePlatform: {
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
        cpuArchitecture: ecs.CpuArchitecture.X86_64,
      },
    });

    const container = this.taskDefinition.addContainer('AgentContainer', {
      containerName: `${agentName}-agent`,
      image: containerImage,
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: `${agentName}-agent`,
        logGroup,
      }),
      essential: true,
      environment: {
        AWS_REGION: cdk.Stack.of(this).region,
        ENVIRONMENT: environment,
        AGENT_NAME: agentName,
        PORT: containerPort.toString(),
        ...environment_vars,
      },
      healthCheck: {
        command: [
          'CMD-SHELL',
          `curl -f http://localhost:${containerPort}${healthCheckPath} || exit 1`,
        ],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
        retries: 3,
        startPeriod: cdk.Duration.seconds(60),
      },
    });

    container.addPortMappings({
      containerPort,
      protocol: ecs.Protocol.TCP,
    });

    // =====================
    // CloudMap Service (HTTP namespace)
    // =====================
    // HTTP namespaces use instance-based health checking (not DNS).
    // We use the L1 CfnService to create the CloudMap service because
    // the namespace prop may be an imported IHttpNamespace (which lacks
    // the createService() method available only on the concrete class).
    // ECS automatically registers/deregisters instances as tasks start/stop.
    const cfnService = new servicediscovery.CfnService(this, 'CloudMapCfnService', {
      name: agentName,
      description: `${agentName} capability agent - ${resourcePrefix}`,
      namespaceId: namespace.namespaceId,
    });

    this.cloudMapService = servicediscovery.Service.fromServiceAttributes(
      this,
      'CloudMapService',
      {
        serviceId: cfnService.attrId,
        serviceArn: cfnService.attrArn,
        serviceName: agentName,
        namespace,
        dnsRecordType: servicediscovery.DnsRecordType.A,
        routingPolicy: servicediscovery.RoutingPolicy.WEIGHTED,
        discoveryType: servicediscovery.DiscoveryType.API,
      }
    );

    // =====================
    // ECS Fargate Service
    // =====================
    this.service = new ecs.FargateService(this, 'Service', {
      serviceName: `${resourcePrefix}-${agentName}-agent`,
      cluster,
      taskDefinition: this.taskDefinition,
      desiredCount,
      securityGroups: [this.securityGroup],
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      assignPublicIp: false,
      enableExecuteCommand: true,
      circuitBreaker: {
        enable: true,
        rollback: true,
      },
    });

    // Associate with CloudMap service for instance registration
    this.service.associateCloudMapService({
      service: this.cloudMapService,
      containerPort,
    });

    // =====================
    // Outputs
    // =====================
    new cdk.CfnOutput(cdk.Stack.of(this), `${agentName}AgentServiceName`, {
      value: this.service.serviceName,
      description: `${agentName} capability agent ECS service name`,
    });
  }
}
