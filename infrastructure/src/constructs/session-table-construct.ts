import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';
import { SSM_PARAMS } from '../ssm-parameters';

/**
 * Props for SessionTableConstruct
 */
export interface SessionTableConstructProps {
  /**
   * Environment name (e.g., 'dev', 'staging', 'prod')
   */
  readonly environment: string;

  /**
   * Project name prefix for resources
   */
  readonly projectName: string;
}

/**
 * DynamoDB table for tracking voice agent sessions across ECS tasks.
 *
 * Enables:
 * - Real-time session counting for auto-scaling decisions
 * - Per-task session tracking
 * - Task health monitoring via heartbeats
 *
 * Table Schema:
 * - PK: SESSION#{session_id} or TASK#{task_id}
 * - SK: METADATA or HEARTBEAT
 *
 * GSI1 (Active sessions):
 * - GSI1PK: STATUS#{status} (e.g., STATUS#active)
 * - GSI1SK: {timestamp}#{session_id}
 *
 * GSI2 (Sessions by task):
 * - GSI2PK: TASK#{task_id}
 * - GSI2SK: {timestamp}#{session_id}
 */
export class SessionTableConstruct extends Construct {
  /** The DynamoDB table */
  public readonly table: dynamodb.Table;

  /** Table name for environment variables */
  public readonly tableName: string;

  /** Table ARN for IAM policies */
  public readonly tableArn: string;

  constructor(scope: Construct, id: string, props: SessionTableConstructProps) {
    super(scope, id);

    const { environment, projectName } = props;
    const resourcePrefix = `${projectName}-${environment}`;

    // =====================
    // DynamoDB Table
    // =====================
    this.table = new dynamodb.Table(this, 'SessionTable', {
      tableName: `${resourcePrefix}-sessions`,
      partitionKey: {
        name: 'PK',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'SK',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY, // Allow deletion in non-prod
      timeToLiveAttribute: 'TTL',
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: environment === 'prod',
      },
    });

    this.tableName = this.table.tableName;
    this.tableArn = this.table.tableArn;

    // =====================
    // GSI1: Query Active Sessions
    // =====================
    // Enables: SELECT COUNT(*) WHERE status = 'active'
    // Usage: table.query(IndexName='GSI1', KeyCondition='GSI1PK = STATUS#active', Select='COUNT')
    this.table.addGlobalSecondaryIndex({
      indexName: 'GSI1',
      partitionKey: {
        name: 'GSI1PK',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'GSI1SK',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // =====================
    // GSI2: Query Sessions by Task
    // =====================
    // Enables: Get all sessions for a specific ECS task
    // Usage: table.query(IndexName='GSI2', KeyCondition='GSI2PK = TASK#{task_id}')
    this.table.addGlobalSecondaryIndex({
      indexName: 'GSI2',
      partitionKey: {
        name: 'GSI2PK',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'GSI2SK',
        type: dynamodb.AttributeType.STRING,
      },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // =====================
    // SSM Parameters
    // =====================
    new ssm.StringParameter(this, 'TableNameParam', {
      parameterName: SSM_PARAMS.SESSION_TABLE_NAME,
      stringValue: this.tableName,
      description: 'Voice Agent Session Tracking DynamoDB Table Name',
    });

    new ssm.StringParameter(this, 'TableArnParam', {
      parameterName: SSM_PARAMS.SESSION_TABLE_ARN,
      stringValue: this.tableArn,
      description: 'Voice Agent Session Tracking DynamoDB Table ARN',
    });

    // =====================
    // Outputs
    // =====================
    new cdk.CfnOutput(this, 'SessionTableName', {
      value: this.tableName,
      description: 'Session tracking DynamoDB table name',
    });

    new cdk.CfnOutput(this, 'SessionTableArn', {
      value: this.tableArn,
      description: 'Session tracking DynamoDB table ARN',
    });
  }
}
