import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as path from 'path';
import { Construct } from 'constructs';
import { VoiceAgentConfig } from '../config';
import { SSM_PARAMS } from '../ssm-parameters';

/**
 * Props for AppointmentStack
 */
export interface AppointmentStackProps extends cdk.StackProps {
  readonly config: VoiceAgentConfig;
}

/**
 * Appointment scheduling infrastructure stack.
 *
 * Creates a DynamoDB table for appointment data and a Lambda-backed REST API
 * for the appointment scheduling capability agent.
 *
 * This is a self-contained appointment system with:
 * - Service types with configurable durations
 * - Business hours enforcement (9AM-5PM weekdays)
 * - Double-booking prevention
 * - Seed data for demos (6 appointments across 3 customers)
 *
 * Standalone stack — no cross-stack dependencies.
 */
export class AppointmentStack extends cdk.Stack {
  /** Appointments DynamoDB table */
  public readonly appointmentsTable: dynamodb.Table;
  /** Appointment API Lambda function */
  public readonly appointmentApiFunction: lambda.Function;
  /** API Gateway REST API */
  public readonly api: apigateway.RestApi;
  /** Appointment API endpoint URL */
  public readonly apiEndpoint: string;

  constructor(scope: Construct, id: string, props: AppointmentStackProps) {
    super(scope, id, props);

    const { config } = props;
    const resourcePrefix = `${config.projectName}-${config.environment}`;

    // ==========================================
    // DynamoDB Table
    // ==========================================

    this.appointmentsTable = new dynamodb.Table(this, 'AppointmentsTable', {
      tableName: `${resourcePrefix}-appointments`,
      partitionKey: { name: 'appointment_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: true,
      },
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    });

    // GSI for customer appointment lookups
    this.appointmentsTable.addGlobalSecondaryIndex({
      indexName: 'customer-index',
      partitionKey: { name: 'customer_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'appointment_date', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI for date-based queries (e.g., all appointments on a given date)
    this.appointmentsTable.addGlobalSecondaryIndex({
      indexName: 'date-index',
      partitionKey: { name: 'appointment_date', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'start_time', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI for status-based queries (e.g., all confirmed appointments)
    this.appointmentsTable.addGlobalSecondaryIndex({
      indexName: 'status-index',
      partitionKey: { name: 'status', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'appointment_date', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // ==========================================
    // Lambda Function for Appointment API
    // ==========================================

    this.appointmentApiFunction = new lambda.Function(this, 'AppointmentApiFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'index.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', 'functions', 'appointment-api')),
      timeout: cdk.Duration.seconds(10),
      memorySize: 512,
      description: `Appointment API handler for voice agent - ${config.environment}`,
      environment: {
        APPOINTMENTS_TABLE: this.appointmentsTable.tableName,
        ENVIRONMENT: config.environment,
        LOG_LEVEL: 'INFO',
      },
    });

    // Grant DynamoDB permissions to Lambda
    this.appointmentsTable.grantReadWriteData(this.appointmentApiFunction);

    // ==========================================
    // API Gateway
    // ==========================================

    this.api = new apigateway.RestApi(this, 'AppointmentApi', {
      restApiName: `${resourcePrefix}-appointment-api`,
      description: `Appointment scheduling API for voice agent - ${config.environment}`,
      deployOptions: {
        stageName: config.environment,
        tracingEnabled: true,
        metricsEnabled: true,
      },
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
        allowHeaders: ['Content-Type', 'Authorization'],
      },
    });

    // ==========================================
    // API Endpoints
    // ==========================================

    const lambdaIntegration = new apigateway.LambdaIntegration(this.appointmentApiFunction);

    // /appointments endpoints
    const appointmentsResource = this.api.root.addResource('appointments');
    appointmentsResource.addMethod('GET', lambdaIntegration); // List appointments (with filters)
    appointmentsResource.addMethod('POST', lambdaIntegration); // Book appointment

    const appointmentResource = appointmentsResource.addResource('{appointmentId}');
    appointmentResource.addMethod('GET', lambdaIntegration); // Get appointment by ID
    appointmentResource.addMethod('PUT', lambdaIntegration); // Reschedule appointment
    appointmentResource.addMethod('DELETE', lambdaIntegration); // Cancel appointment

    // Sub-resources for cancel and reschedule (used by appointment agent client)
    const cancelResource = appointmentResource.addResource('cancel');
    cancelResource.addMethod('POST', lambdaIntegration); // Cancel appointment via POST

    const rescheduleResource = appointmentResource.addResource('reschedule');
    rescheduleResource.addMethod('POST', lambdaIntegration); // Reschedule appointment via POST

    // /availability endpoint
    const availabilityResource = this.api.root.addResource('availability');
    availabilityResource.addMethod('GET', lambdaIntegration); // Check available slots

    // /service-types endpoint
    const serviceTypesResource = this.api.root.addResource('service-types');
    serviceTypesResource.addMethod('GET', lambdaIntegration); // List service types

    // /admin endpoints (demo data management)
    const adminResource = this.api.root.addResource('admin');

    const seedResource = adminResource.addResource('seed');
    seedResource.addMethod('POST', lambdaIntegration); // Load demo data

    const resetResource = adminResource.addResource('reset');
    resetResource.addMethod('DELETE', lambdaIntegration); // Clear all data

    // /health endpoint
    const healthResource = this.api.root.addResource('health');
    healthResource.addMethod('GET', lambdaIntegration);

    // Store API endpoint
    this.apiEndpoint = this.api.url;

    // ==========================================
    // SSM Parameters for Cross-Stack Reference
    // ==========================================

    new ssm.StringParameter(this, 'AppointmentApiUrlParam', {
      parameterName: SSM_PARAMS.APPOINTMENT_API_URL,
      stringValue: this.apiEndpoint,
      description: 'Appointment API Gateway endpoint URL',
    });

    new ssm.StringParameter(this, 'AppointmentTableNameParam', {
      parameterName: SSM_PARAMS.APPOINTMENT_TABLE_NAME,
      stringValue: this.appointmentsTable.tableName,
      description: 'Appointments DynamoDB table name',
    });

    // ==========================================
    // CloudWatch Metrics and Alarms
    // ==========================================

    // API Gateway 4xx Error Rate Alarm
    new cloudwatch.Alarm(this, 'Api4xxErrorRateAlarm', {
      alarmName: `${resourcePrefix}-appointment-api-4xx-errors`,
      metric: this.api.metricClientError({
        period: cdk.Duration.minutes(5),
        statistic: 'sum',
      }),
      threshold: 10,
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      alarmDescription: 'Appointment API 4xx error rate is high',
    });

    // API Gateway 5xx Error Rate Alarm
    new cloudwatch.Alarm(this, 'Api5xxErrorRateAlarm', {
      alarmName: `${resourcePrefix}-appointment-api-5xx-errors`,
      metric: this.api.metricServerError({
        period: cdk.Duration.minutes(5),
        statistic: 'sum',
      }),
      threshold: 5,
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      alarmDescription: 'Appointment API 5xx error rate is high',
    });

    // API Gateway Latency Alarm
    new cloudwatch.Alarm(this, 'ApiLatencyAlarm', {
      alarmName: `${resourcePrefix}-appointment-api-latency`,
      metric: this.api.metricLatency({
        period: cdk.Duration.minutes(5),
        statistic: 'avg',
      }),
      threshold: 1000,
      evaluationPeriods: 3,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      alarmDescription: 'Appointment API average latency is above 1 second',
    });

    // Lambda Error Rate Alarm
    new cloudwatch.Alarm(this, 'LambdaErrorRateAlarm', {
      alarmName: `${resourcePrefix}-appointment-lambda-errors`,
      metric: this.appointmentApiFunction.metricErrors({
        period: cdk.Duration.minutes(5),
        statistic: 'sum',
      }),
      threshold: 5,
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      alarmDescription: 'Appointment Lambda error count is high',
    });

    // Lambda Throttles Alarm
    new cloudwatch.Alarm(this, 'LambdaThrottlesAlarm', {
      alarmName: `${resourcePrefix}-appointment-lambda-throttles`,
      metric: this.appointmentApiFunction.metricThrottles({
        period: cdk.Duration.minutes(5),
        statistic: 'sum',
      }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      alarmDescription: 'Appointment Lambda is being throttled',
    });

    // DynamoDB Read Throttles Alarm
    new cloudwatch.Alarm(this, 'DynamoDBReadThrottlesAlarm', {
      alarmName: `${resourcePrefix}-appointment-dynamodb-read-throttles`,
      metric: this.appointmentsTable.metricThrottledRequestsForOperations({
        operations: [dynamodb.Operation.GET_ITEM, dynamodb.Operation.QUERY],
        period: cdk.Duration.minutes(5),
        statistic: 'sum',
      }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      alarmDescription: 'DynamoDB read requests are being throttled',
    });

    // ==========================================
    // CloudWatch Dashboard
    // ==========================================

    const dashboard = new cloudwatch.Dashboard(this, 'AppointmentDashboard', {
      dashboardName: `${resourcePrefix}-appointment-dashboard`,
    });

    dashboard.addWidgets(
      // API Gateway Metrics
      new cloudwatch.GraphWidget({
        title: 'API Gateway - Requests & Errors',
        left: [
          this.api.metricCount({ period: cdk.Duration.minutes(1) }),
          this.api.metricClientError({ period: cdk.Duration.minutes(1) }),
          this.api.metricServerError({ period: cdk.Duration.minutes(1) }),
        ],
        width: 12,
      }),
      new cloudwatch.GraphWidget({
        title: 'API Gateway - Latency',
        left: [
          this.api.metricLatency({ period: cdk.Duration.minutes(1) }),
        ],
        width: 12,
      }),
      // Lambda Metrics
      new cloudwatch.GraphWidget({
        title: 'Lambda - Invocations & Errors',
        left: [
          this.appointmentApiFunction.metricInvocations({ period: cdk.Duration.minutes(1) }),
          this.appointmentApiFunction.metricErrors({ period: cdk.Duration.minutes(1) }),
        ],
        width: 12,
      }),
      new cloudwatch.GraphWidget({
        title: 'Lambda - Duration',
        left: [
          this.appointmentApiFunction.metricDuration({ period: cdk.Duration.minutes(1) }),
        ],
        width: 12,
      }),
      // DynamoDB Metrics
      new cloudwatch.GraphWidget({
        title: 'DynamoDB - Consumed Capacity',
        left: [
          this.appointmentsTable.metricConsumedReadCapacityUnits({ period: cdk.Duration.minutes(1) }),
          this.appointmentsTable.metricConsumedWriteCapacityUnits({ period: cdk.Duration.minutes(1) }),
        ],
        width: 12,
      }),
      new cloudwatch.GraphWidget({
        title: 'DynamoDB - Throttled Requests',
        left: [
          this.appointmentsTable.metricThrottledRequestsForOperations({
            operations: [dynamodb.Operation.GET_ITEM, dynamodb.Operation.QUERY, dynamodb.Operation.PUT_ITEM],
            period: cdk.Duration.minutes(1),
          }),
        ],
        width: 12,
      })
    );

    // ==========================================
    // CloudFormation Outputs
    // ==========================================

    new cdk.CfnOutput(this, 'AppointmentApiUrl', {
      value: this.apiEndpoint,
      description: 'Appointment API Gateway endpoint URL',
    });

    new cdk.CfnOutput(this, 'AppointmentsTableName', {
      value: this.appointmentsTable.tableName,
      description: 'Appointments DynamoDB table name',
    });

    new cdk.CfnOutput(this, 'AppointmentDashboardUrl', {
      value: `https://${this.region}.console.aws.amazon.com/cloudwatch/home?region=${this.region}#dashboards:name=${resourcePrefix}-appointment-dashboard`,
      description: 'Appointment CloudWatch Dashboard URL',
    });
  }
}
