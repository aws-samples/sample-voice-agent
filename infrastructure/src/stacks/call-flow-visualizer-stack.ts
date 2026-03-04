import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as logsDestinations from 'aws-cdk-lib/aws-logs-destinations';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as path from 'path';
import { Construct } from 'constructs';
import { VoiceAgentConfig } from '../config';
import { SSM_PARAMS } from '../ssm-parameters';

/**
 * Props for CallFlowVisualizerStack
 */
export interface CallFlowVisualizerStackProps extends cdk.StackProps {
  readonly config: VoiceAgentConfig;
}

/**
 * Optional, bolt-on stack for the Call Flow Visualizer.
 *
 * Deploys:
 * - DynamoDB event store for call events
 * - Ingester Lambda triggered by CW Logs subscription filter
 * - Query Lambda behind API Gateway for timeline retrieval
 *
 * This stack makes no changes to the voice agent or existing stacks.
 * It reads logs from CloudWatch via a subscription filter and enriches
 * with session data from the existing sessions table (read-only).
 *
 * Enable with: -c voice-agent:enableCallFlowVisualizer=true
 */
export class CallFlowVisualizerStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: CallFlowVisualizerStackProps) {
    super(scope, id, props);

    const { config } = props;
    const resourcePrefix = `${config.projectName}-${config.environment}`;

    // =====================
    // Cross-stack references (read-only)
    // =====================
    const logGroupName = ssm.StringParameter.valueFromLookup(
      this,
      SSM_PARAMS.TASK_LOG_GROUP_NAME
    );
    const sessionTableName = ssm.StringParameter.valueFromLookup(
      this,
      SSM_PARAMS.SESSION_TABLE_NAME
    );
    const sessionTableArn = ssm.StringParameter.valueFromLookup(
      this,
      SSM_PARAMS.SESSION_TABLE_ARN
    );

    // =====================
    // Call Events DynamoDB Table
    // =====================
    const eventsTable = new dynamodb.Table(this, 'CallEventsTable', {
      tableName: `${resourcePrefix}-call-events`,
      partitionKey: { name: 'PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'SK', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'TTL',
      removalPolicy:
        config.environment === 'prod'
          ? cdk.RemovalPolicy.RETAIN
          : cdk.RemovalPolicy.DESTROY,
    });

    // GSI1: Calls by date + disposition
    eventsTable.addGlobalSecondaryIndex({
      indexName: 'GSI1',
      partitionKey: { name: 'GSI1PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'GSI1SK', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI2: Calls by tool usage
    eventsTable.addGlobalSecondaryIndex({
      indexName: 'GSI2',
      partitionKey: { name: 'GSI2PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'GSI2SK', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // =====================
    // Ingester Lambda
    // =====================
    const ingesterLogGroup = new logs.LogGroup(this, 'IngesterLogGroup', {
      logGroupName: `/aws/lambda/${resourcePrefix}-call-flow-ingester`,
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const ingesterFn = new lambda.Function(this, 'IngesterFunction', {
      functionName: `${resourcePrefix}-call-flow-ingester`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset(
        path.join(__dirname, '..', 'functions', 'call-flow-ingester'),
        {
          bundling: {
            image: lambda.Runtime.PYTHON_3_12.bundlingImage,
            command: [
              'bash',
              '-c',
              'pip install -r requirements.txt -t /asset-output && cp -au . /asset-output',
            ],
          },
        }
      ),
      timeout: cdk.Duration.seconds(60),
      memorySize: 256,
      environment: {
        EVENTS_TABLE_NAME: eventsTable.tableName,
        EVENT_TTL_DAYS: '30',
      },
      logGroup: ingesterLogGroup,
    });

    // Ingester: write to events table
    ingesterFn.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'DynamoDBBatchWrite',
        effect: iam.Effect.ALLOW,
        actions: ['dynamodb:BatchWriteItem'],
        resources: [eventsTable.tableArn],
      })
    );

    // =====================
    // CW Logs Subscription Filter
    // =====================
    const voiceAgentLogGroup = logs.LogGroup.fromLogGroupName(
      this,
      'VoiceAgentLogGroup',
      logGroupName
    );

    new logs.SubscriptionFilter(this, 'EventIngestionFilter', {
      logGroup: voiceAgentLogGroup,
      destination: new logsDestinations.LambdaDestination(ingesterFn),
      filterPattern: logs.FilterPattern.any(
        logs.FilterPattern.stringValue('$.event', '=', 'conversation_turn'),
        logs.FilterPattern.stringValue('$.event', '=', 'turn_completed'),
        logs.FilterPattern.stringValue('$.event', '=', 'tool_execution'),
        logs.FilterPattern.stringValue('$.event', '=', 'barge_in'),
        logs.FilterPattern.stringValue('$.event', '=', 'session_started'),
        logs.FilterPattern.stringValue('$.event', '=', 'session_ended'),
        logs.FilterPattern.stringValue('$.event', '=', 'a2a_tool_call_start'),
        logs.FilterPattern.stringValue('$.event', '=', 'a2a_tool_call_success'),
        logs.FilterPattern.stringValue('$.event', '=', 'a2a_tool_call_cache_hit'),
        logs.FilterPattern.stringValue('$.event', '=', 'a2a_tool_call_timeout'),
        logs.FilterPattern.stringValue('$.event', '=', 'a2a_tool_call_error'),
        logs.FilterPattern.stringValue('$.event', '=', 'call_metrics_summary'),
        logs.FilterPattern.stringValue('$.event', '=', 'audio_clipping_detected'),
        logs.FilterPattern.stringValue('$.event', '=', 'poor_audio_detected')
      ),
      filterName: `${resourcePrefix}-call-flow-ingestion`,
    });

    // =====================
    // Query Lambda
    // =====================
    const queryLogGroup = new logs.LogGroup(this, 'QueryLogGroup', {
      logGroupName: `/aws/lambda/${resourcePrefix}-call-flow-api`,
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const queryFn = new lambda.Function(this, 'QueryFunction', {
      functionName: `${resourcePrefix}-call-flow-api`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset(
        path.join(__dirname, '..', 'functions', 'call-flow-api'),
        {
          bundling: {
            image: lambda.Runtime.PYTHON_3_12.bundlingImage,
            command: [
              'bash',
              '-c',
              'pip install -r requirements.txt -t /asset-output && cp -au . /asset-output',
            ],
          },
        }
      ),
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      environment: {
        EVENTS_TABLE_NAME: eventsTable.tableName,
        SESSION_TABLE_NAME: sessionTableName,
      },
      logGroup: queryLogGroup,
    });

    // Query: read from events table
    queryFn.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'DynamoDBEventsRead',
        effect: iam.Effect.ALLOW,
        actions: ['dynamodb:Query', 'dynamodb:GetItem'],
        resources: [
          eventsTable.tableArn,
          `${eventsTable.tableArn}/index/*`,
        ],
      })
    );

    // Query: read from sessions table (enrichment)
    queryFn.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'DynamoDBSessionsRead',
        effect: iam.Effect.ALLOW,
        actions: ['dynamodb:GetItem'],
        resources: [sessionTableArn],
      })
    );

    // =====================
    // API Gateway
    // =====================
    const api = new apigateway.RestApi(this, 'CallFlowApi', {
      restApiName: `${resourcePrefix}-call-flow-api`,
      description: 'Call Flow Visualizer API',
      deployOptions: {
        stageName: config.environment,
      },
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: [
          'Content-Type',
          'Authorization',
          'X-Amz-Date',
          'X-Api-Key',
          'X-Amz-Security-Token',
        ],
      },
    });

    const queryIntegration = new apigateway.LambdaIntegration(queryFn, {
      proxy: true,
    });

    // /api
    const apiResource = api.root.addResource('api');

    // /api/calls
    const callsResource = apiResource.addResource('calls');
    callsResource.addMethod('GET', queryIntegration);

    // /api/calls/{call_id}
    const callResource = callsResource.addResource('{call_id}');
    callResource.addMethod('GET', queryIntegration);

    // /api/calls/{call_id}/summary
    const summaryResource = callResource.addResource('summary');
    summaryResource.addMethod('GET', queryIntegration);

    // /api/search
    const searchResource = apiResource.addResource('search');
    searchResource.addMethod('GET', queryIntegration);

    // =====================
    // S3 Bucket for SPA
    // =====================
    const spaBucket = new s3.Bucket(this, 'SpaBucket', {
      bucketName: `${resourcePrefix}-call-flow-ui-${this.account}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    // =====================
    // CloudFront Distribution
    // =====================

    // Parse API Gateway URL to extract domain and stage path
    // api.url is a token like https://{restApiId}.execute-api.{region}.amazonaws.com/{stage}/
    const apiDomainName = `${api.restApiId}.execute-api.${this.region}.amazonaws.com`;

    const distribution = new cloudfront.Distribution(this, 'Distribution', {
      comment: `${resourcePrefix} Call Flow Visualizer`,
      defaultRootObject: 'index.html',
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(spaBucket),
        viewerProtocolPolicy:
          cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
      },
      additionalBehaviors: {
        '/api/*': {
          origin: new origins.HttpOrigin(apiDomainName, {
            originPath: `/${config.environment}`,
            protocolPolicy: cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
          }),
          viewerProtocolPolicy:
            cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy:
            cloudfront.OriginRequestPolicy
              .ALL_VIEWER_EXCEPT_HOST_HEADER,
        },
      },
      errorResponses: [
        {
          httpStatus: 403,
          responseHttpStatus: 200,
          responsePagePath: '/index.html',
          ttl: cdk.Duration.seconds(0),
        },
        {
          httpStatus: 404,
          responseHttpStatus: 200,
          responsePagePath: '/index.html',
          ttl: cdk.Duration.seconds(0),
        },
      ],
    });

    // =====================
    // SPA Deployment
    // =====================
    new s3deploy.BucketDeployment(this, 'SpaDeployment', {
      sources: [
        s3deploy.Source.asset(
          path.join(__dirname, '..', '..', '..', 'frontend', 'call-flow-visualizer'),
          {
            bundling: {
              image: cdk.DockerImage.fromRegistry('node:20-slim'),
              command: [
                'bash',
                '-c',
                'npm ci && npm run build && cp -r dist/* /asset-output/',
              ],
              environment: {
                HOME: '/tmp',
              },
            },
          }
        ),
      ],
      destinationBucket: spaBucket,
      distribution,
      distributionPaths: ['/*'],
    });

    // =====================
    // Outputs
    // =====================
    new cdk.CfnOutput(this, 'CloudFrontUrl', {
      value: `https://${distribution.distributionDomainName}`,
      description: 'Call Flow Visualizer URL',
    });

    new cdk.CfnOutput(this, 'ApiUrl', {
      value: api.url,
      description: 'Call Flow Visualizer API URL (direct)',
    });

    new cdk.CfnOutput(this, 'EventsTableName', {
      value: eventsTable.tableName,
      description: 'Call Events DynamoDB Table Name',
    });
  }
}
