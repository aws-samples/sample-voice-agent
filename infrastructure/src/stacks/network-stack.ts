import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { VoiceAgentConfig } from '../config';
import { VpcConstruct } from '../constructs';

/**
 * Props for NetworkStack
 */
export interface NetworkStackProps extends cdk.StackProps {
  readonly config: VoiceAgentConfig;
}

/**
 * Network infrastructure stack.
 * Thin wrapper that delegates to VpcConstruct.
 *
 * Creates VPC with public, private, and isolated subnets,
 * NAT gateways, and security groups.
 */
export class NetworkStack extends cdk.Stack {
  /** VPC construct containing all network resources */
  public readonly vpcConstruct: VpcConstruct;

  constructor(scope: Construct, id: string, props: NetworkStackProps) {
    super(scope, id, props);

    const { config } = props;

    // Delegate to VpcConstruct
    this.vpcConstruct = new VpcConstruct(this, 'Vpc', {
      environment: config.environment,
      projectName: config.projectName,
      cidr: config.vpcCidr,
      maxAzs: config.maxAzs,
      natGateways: config.natGateways,
    });

    // CloudFormation outputs (for console visibility)
    new cdk.CfnOutput(this, 'VpcId', {
      value: this.vpcConstruct.vpc.vpcId,
      description: 'VPC ID',
    });
  }
}
