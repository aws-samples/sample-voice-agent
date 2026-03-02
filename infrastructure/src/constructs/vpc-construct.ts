import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { SSM_PARAMS } from '../ssm-parameters';

/**
 * Props for VpcConstruct
 */
export interface VpcConstructProps {
  /** Deployment environment */
  environment: string;
  /** Project name for resource naming */
  projectName: string;
  /** VPC CIDR block */
  cidr: string;
  /** Maximum availability zones */
  maxAzs: number;
  /** Number of NAT gateways */
  natGateways: number;
}

/**
 * VPC infrastructure construct.
 * Creates VPC with public, private, and isolated subnets,
 * NAT gateways, VPC endpoints, and security groups.
 *
 * VPC Endpoints:
 * - S3 Gateway: For ECR image layers, CloudWatch logs
 * - SageMaker Runtime: For invoking Deepgram STT/TTS models
 * - Secrets Manager: For reading API keys
 * - Bedrock Runtime: For Claude LLM inference
 *
 * Outputs are stored in SSM Parameters for cross-stack reference.
 */
export class VpcConstruct extends Construct {
  /** The VPC created by this construct */
  public readonly vpc: ec2.IVpc;
  /** Security group for SageMaker endpoints */
  public readonly sagemakerSecurityGroup: ec2.ISecurityGroup;
  /** Security group for Lambda functions */
  public readonly lambdaSecurityGroup: ec2.ISecurityGroup;
  /** Security group for VPC interface endpoints */
  public readonly vpcEndpointSecurityGroup: ec2.ISecurityGroup;

  constructor(scope: Construct, id: string, props: VpcConstructProps) {
    super(scope, id);

    // Validate required props
    if (!props.cidr) {
      throw new Error(`${id}: cidr is required in props`);
    }
    if (props.maxAzs < 1 || props.maxAzs > 6) {
      throw new Error(`${id}: maxAzs must be between 1 and 6`);
    }

    const resourcePrefix = `${props.projectName}-${props.environment}`;

    // VPC with public, private, and isolated subnets
    this.vpc = new ec2.Vpc(this, 'Vpc', {
      ipAddresses: ec2.IpAddresses.cidr(props.cidr),
      maxAzs: props.maxAzs,
      natGateways: props.natGateways,
      subnetConfiguration: [
        {
          name: 'public',
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
        {
          name: 'private',
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
          cidrMask: 24,
        },
        {
          name: 'isolated',
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
        },
      ],
    });

    // Security group for SageMaker endpoints
    this.sagemakerSecurityGroup = new ec2.SecurityGroup(this, 'SageMakerSG', {
      vpc: this.vpc,
      description: `Security group for SageMaker Deepgram endpoints - ${resourcePrefix}`,
      allowAllOutbound: false,
    });

    // Security group for Lambda functions
    this.lambdaSecurityGroup = new ec2.SecurityGroup(this, 'LambdaSG', {
      vpc: this.vpc,
      description: `Security group for Lambda functions - ${resourcePrefix}`,
      allowAllOutbound: true,
    });

    // Security group for VPC interface endpoints
    this.vpcEndpointSecurityGroup = new ec2.SecurityGroup(this, 'VpcEndpointSG', {
      vpc: this.vpc,
      description: `Security group for VPC interface endpoints - ${resourcePrefix}`,
      allowAllOutbound: false,
    });

    // Allow Lambda to communicate with SageMaker
    this.sagemakerSecurityGroup.addIngressRule(
      this.lambdaSecurityGroup,
      ec2.Port.tcp(443),
      'Allow HTTPS from Lambda'
    );

    // Allow Lambda to communicate with VPC endpoints
    this.vpcEndpointSecurityGroup.addIngressRule(
      this.lambdaSecurityGroup,
      ec2.Port.tcp(443),
      'Allow HTTPS from Lambda to VPC endpoints'
    );

    // =====================
    // VPC Gateway Endpoints
    // =====================

    // S3 Gateway Endpoint - for ECR image layers, CloudWatch logs, etc.
    this.vpc.addGatewayEndpoint('S3Endpoint', {
      service: ec2.GatewayVpcEndpointAwsService.S3,
      subnets: [
        { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
        { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      ],
    });

    // ========================
    // VPC Interface Endpoints
    // ========================

    // SageMaker Runtime Endpoint - for invoking Deepgram STT/TTS models
    // Handles both standard InvokeEndpoint (port 443) and BiDi streaming
    // (HTTP/2 on port 8443). Private DNS enabled so runtime.sagemaker.<region>.amazonaws.com
    // resolves to the VPC endpoint ENI, keeping all SageMaker traffic off the NAT gateway.
    // Requires port 8443 ingress on the VPC endpoint security group (configured in ecs-stack.ts).
    // Validated 2026-02-24: BiDi streaming confirmed working through VPC endpoint.
    this.vpc.addInterfaceEndpoint('SageMakerRuntimeEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.SAGEMAKER_RUNTIME,
      subnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [this.vpcEndpointSecurityGroup],
      privateDnsEnabled: true,
    });

    // Secrets Manager Endpoint - for reading API keys (Daily, Deepgram)
    this.vpc.addInterfaceEndpoint('SecretsManagerEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
      subnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [this.vpcEndpointSecurityGroup],
      privateDnsEnabled: true,
    });

    // Bedrock Runtime Endpoint - for Claude LLM inference
    this.vpc.addInterfaceEndpoint('BedrockRuntimeEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME,
      subnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [this.vpcEndpointSecurityGroup],
      privateDnsEnabled: true,
    });

    // CloudWatch Logs Endpoint - for Lambda and container logging
    this.vpc.addInterfaceEndpoint('CloudWatchLogsEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
      subnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [this.vpcEndpointSecurityGroup],
      privateDnsEnabled: true,
    });

    // Store outputs in SSM Parameters for cross-stack reference
    new ssm.StringParameter(this, 'VpcIdParam', {
      parameterName: SSM_PARAMS.VPC_ID,
      stringValue: this.vpc.vpcId,
      description: 'Voice Agent VPC ID',
    });

    new ssm.StringParameter(this, 'PrivateSubnetIdsParam', {
      parameterName: SSM_PARAMS.PRIVATE_SUBNET_IDS,
      stringValue: this.vpc
        .selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS })
        .subnetIds.join(','),
      description: 'Voice Agent private subnet IDs (comma-separated)',
    });

    new ssm.StringParameter(this, 'IsolatedSubnetIdsParam', {
      parameterName: SSM_PARAMS.ISOLATED_SUBNET_IDS,
      stringValue: this.vpc
        .selectSubnets({ subnetType: ec2.SubnetType.PRIVATE_ISOLATED })
        .subnetIds.join(','),
      description: 'Voice Agent isolated subnet IDs (comma-separated)',
    });

    new ssm.StringParameter(this, 'SageMakerSgIdParam', {
      parameterName: SSM_PARAMS.SAGEMAKER_SG_ID,
      stringValue: this.sagemakerSecurityGroup.securityGroupId,
      description: 'Voice Agent SageMaker security group ID',
    });

    new ssm.StringParameter(this, 'LambdaSgIdParam', {
      parameterName: SSM_PARAMS.LAMBDA_SG_ID,
      stringValue: this.lambdaSecurityGroup.securityGroupId,
      description: 'Voice Agent Lambda security group ID',
    });

    new ssm.StringParameter(this, 'VpcEndpointSgIdParam', {
      parameterName: SSM_PARAMS.VPC_ENDPOINT_SG_ID,
      stringValue: this.vpcEndpointSecurityGroup.securityGroupId,
      description: 'Voice Agent VPC endpoint security group ID',
    });
  }
}
