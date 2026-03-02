import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as path from 'path';
import { Construct } from 'constructs';
import { VoiceAgentConfig } from '../config';
import { SSM_PARAMS } from '../ssm-parameters';

/**
 * Props for CrmStack
 */
export interface CrmStackProps extends cdk.StackProps {
  readonly config: VoiceAgentConfig;
}

/**
 * CRM infrastructure stack.
 *
 * Creates DynamoDB tables for customer data, cases, and interactions,
 * along with a Lambda-backed REST API for voice agent integration.
 *
 * This is a self-hosted CRM solution that eliminates external dependencies
 * while providing customer context for voice agent interactions.
 */
export class CrmStack extends cdk.Stack {
  /** Customers DynamoDB table */
  public readonly customersTable: dynamodb.Table;
  /** Cases DynamoDB table */
  public readonly casesTable: dynamodb.Table;
  /** Interactions DynamoDB table */
  public readonly interactionsTable: dynamodb.Table;
  /** CRM API Lambda function */
  public readonly crmApiFunction: lambda.Function;
  /** API Gateway REST API */
  public readonly api: apigateway.RestApi;
  /** CRM API endpoint URL */
  public readonly apiEndpoint: string;

  constructor(scope: Construct, id: string, props: CrmStackProps) {
    super(scope, id, props);

    const { config } = props;
    const resourcePrefix = `${config.projectName}-${config.environment}`;

    // ==========================================
    // DynamoDB Tables
    // ==========================================

    // Customers Table
    this.customersTable = new dynamodb.Table(this, 'CustomersTable', {
      tableName: `${resourcePrefix}-crm-customers`,
      partitionKey: { name: 'customer_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: true,
      },
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    });

    // GSI for phone lookups (primary search method)
    this.customersTable.addGlobalSecondaryIndex({
      indexName: 'phone-index',
      partitionKey: { name: 'phone', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI for email lookups
    this.customersTable.addGlobalSecondaryIndex({
      indexName: 'email-index',
      partitionKey: { name: 'email', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // Cases Table
    this.casesTable = new dynamodb.Table(this, 'CasesTable', {
      tableName: `${resourcePrefix}-crm-cases`,
      partitionKey: { name: 'case_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'customer_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: true,
      },
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    });

    // GSI for customer case lookups
    this.casesTable.addGlobalSecondaryIndex({
      indexName: 'customer-index',
      partitionKey: { name: 'customer_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'created_at', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI for status-based queries (e.g., all open cases)
    this.casesTable.addGlobalSecondaryIndex({
      indexName: 'status-index',
      partitionKey: { name: 'status', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'created_at', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // Interactions Table (Call History)
    this.interactionsTable = new dynamodb.Table(this, 'InteractionsTable', {
      tableName: `${resourcePrefix}-crm-interactions`,
      partitionKey: { name: 'interaction_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'customer_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: true,
      },
      encryption: dynamodb.TableEncryption.AWS_MANAGED,
    });

    // GSI for customer interaction history
    this.interactionsTable.addGlobalSecondaryIndex({
      indexName: 'customer-index',
      partitionKey: { name: 'customer_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'start_time', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // GSI for session lookups
    this.interactionsTable.addGlobalSecondaryIndex({
      indexName: 'session-index',
      partitionKey: { name: 'session_id', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // ==========================================
    // Lambda Function for CRM API
    // ==========================================

    this.crmApiFunction = new lambda.Function(this, 'CrmApiFunction', {
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'index.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', 'functions', 'crm-api')),
      timeout: cdk.Duration.seconds(10),
      memorySize: 512,
      description: `CRM API handler for voice agent - ${config.environment}`,
      environment: {
        CUSTOMERS_TABLE: this.customersTable.tableName,
        CASES_TABLE: this.casesTable.tableName,
        INTERACTIONS_TABLE: this.interactionsTable.tableName,
        ENVIRONMENT: config.environment,
        LOG_LEVEL: 'INFO',
      },
    });

    // Grant DynamoDB permissions to Lambda
    this.customersTable.grantReadWriteData(this.crmApiFunction);
    this.casesTable.grantReadWriteData(this.crmApiFunction);
    this.interactionsTable.grantReadWriteData(this.crmApiFunction);

    // ==========================================
    // API Gateway
    // ==========================================

    this.api = new apigateway.RestApi(this, 'CrmApi', {
      restApiName: `${resourcePrefix}-crm-api`,
      description: `CRM API for voice agent customer data - ${config.environment}`,
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

    const lambdaIntegration = new apigateway.LambdaIntegration(this.crmApiFunction);

    // /customers endpoints
    const customersResource = this.api.root.addResource('customers');
    customersResource.addMethod('GET', lambdaIntegration); // Search by phone/email
    customersResource.addMethod('POST', lambdaIntegration); // Create customer

    const customerResource = customersResource.addResource('{customerId}');
    customerResource.addMethod('GET', lambdaIntegration); // Get customer by ID
    customerResource.addMethod('PUT', lambdaIntegration); // Update customer

    const customerCasesResource = customerResource.addResource('cases');
    customerCasesResource.addMethod('GET', lambdaIntegration); // Get customer's cases

    const customerInteractionsResource = customerResource.addResource('interactions');
    customerInteractionsResource.addMethod('GET', lambdaIntegration); // Get customer's interactions

    // /cases endpoints
    const casesResource = this.api.root.addResource('cases');
    casesResource.addMethod('GET', lambdaIntegration); // List cases (with filters)
    casesResource.addMethod('POST', lambdaIntegration); // Create case

    const caseResource = casesResource.addResource('{caseId}');
    caseResource.addMethod('GET', lambdaIntegration); // Get case by ID
    caseResource.addMethod('PUT', lambdaIntegration); // Update case

    const caseNotesResource = caseResource.addResource('notes');
    caseNotesResource.addMethod('POST', lambdaIntegration); // Add note to case

    // /interactions endpoints
    const interactionsResource = this.api.root.addResource('interactions');
    interactionsResource.addMethod('POST', lambdaIntegration); // Log interaction

    const interactionResource = interactionsResource.addResource('{interactionId}');
    interactionResource.addMethod('GET', lambdaIntegration); // Get interaction
    interactionResource.addMethod('PUT', lambdaIntegration); // Update interaction

    // /admin endpoints (demo data management)
    const adminResource = this.api.root.addResource('admin');

    const seedResource = adminResource.addResource('seed');
    seedResource.addMethod('POST', lambdaIntegration); // Load demo data

    const resetResource = adminResource.addResource('reset');
    resetResource.addMethod('DELETE', lambdaIntegration); // Clear all data

    // Store API endpoint
    this.apiEndpoint = this.api.url;

    // ==========================================
    // SSM Parameters for Cross-Stack Reference
    // ==========================================

    new ssm.StringParameter(this, 'CrmApiUrlParam', {
      parameterName: SSM_PARAMS.CRM_API_URL,
      stringValue: this.apiEndpoint,
      description: 'CRM API Gateway endpoint URL',
    });

    new ssm.StringParameter(this, 'CrmCustomersTableNameParam', {
      parameterName: SSM_PARAMS.CRM_CUSTOMERS_TABLE_NAME,
      stringValue: this.customersTable.tableName,
      description: 'CRM Customers DynamoDB table name',
    });

    new ssm.StringParameter(this, 'CrmCasesTableNameParam', {
      parameterName: SSM_PARAMS.CRM_CASES_TABLE_NAME,
      stringValue: this.casesTable.tableName,
      description: 'CRM Cases DynamoDB table name',
    });

    new ssm.StringParameter(this, 'CrmInteractionsTableNameParam', {
      parameterName: SSM_PARAMS.CRM_INTERACTIONS_TABLE_NAME,
      stringValue: this.interactionsTable.tableName,
      description: 'CRM Interactions DynamoDB table name',
    });

    // ==========================================
    // CloudWatch Metrics and Alarms
    // ==========================================

    // API Gateway 4xx Error Rate Alarm
    const api4xxErrorRate = new cloudwatch.Alarm(this, 'Api4xxErrorRateAlarm', {
      alarmName: `${resourcePrefix}-crm-api-4xx-errors`,
      metric: this.api.metricClientError({
        period: cdk.Duration.minutes(5),
        statistic: 'sum',
      }),
      threshold: 10,
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      alarmDescription: 'CRM API 4xx error rate is high',
    });

    // API Gateway 5xx Error Rate Alarm
    const api5xxErrorRate = new cloudwatch.Alarm(this, 'Api5xxErrorRateAlarm', {
      alarmName: `${resourcePrefix}-crm-api-5xx-errors`,
      metric: this.api.metricServerError({
        period: cdk.Duration.minutes(5),
        statistic: 'sum',
      }),
      threshold: 5,
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      alarmDescription: 'CRM API 5xx error rate is high',
    });

    // API Gateway Latency Alarm
    const apiLatencyAlarm = new cloudwatch.Alarm(this, 'ApiLatencyAlarm', {
      alarmName: `${resourcePrefix}-crm-api-latency`,
      metric: this.api.metricLatency({
        period: cdk.Duration.minutes(5),
        statistic: 'avg',
      }),
      threshold: 1000, // 1 second
      evaluationPeriods: 3,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      alarmDescription: 'CRM API average latency is above 1 second',
    });

    // Lambda Error Rate Alarm
    const lambdaErrorRate = new cloudwatch.Alarm(this, 'LambdaErrorRateAlarm', {
      alarmName: `${resourcePrefix}-crm-lambda-errors`,
      metric: this.crmApiFunction.metricErrors({
        period: cdk.Duration.minutes(5),
        statistic: 'sum',
      }),
      threshold: 5,
      evaluationPeriods: 2,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      alarmDescription: 'CRM Lambda error count is high',
    });

    // Lambda Throttles Alarm
    const lambdaThrottles = new cloudwatch.Alarm(this, 'LambdaThrottlesAlarm', {
      alarmName: `${resourcePrefix}-crm-lambda-throttles`,
      metric: this.crmApiFunction.metricThrottles({
        period: cdk.Duration.minutes(5),
        statistic: 'sum',
      }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      alarmDescription: 'CRM Lambda is being throttled',
    });

    // DynamoDB Read/Write Capacity Alarms
    const dynamoDBReadThrottles = new cloudwatch.Alarm(this, 'DynamoDBReadThrottlesAlarm', {
      alarmName: `${resourcePrefix}-crm-dynamodb-read-throttles`,
      metric: this.customersTable.metricThrottledRequestsForOperations({
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

    const dashboard = new cloudwatch.Dashboard(this, 'CrmDashboard', {
      dashboardName: `${resourcePrefix}-crm-dashboard`,
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
          this.crmApiFunction.metricInvocations({ period: cdk.Duration.minutes(1) }),
          this.crmApiFunction.metricErrors({ period: cdk.Duration.minutes(1) }),
        ],
        width: 12,
      }),
      new cloudwatch.GraphWidget({
        title: 'Lambda - Duration',
        left: [
          this.crmApiFunction.metricDuration({ period: cdk.Duration.minutes(1) }),
        ],
        width: 12,
      }),
      // DynamoDB Metrics
      new cloudwatch.GraphWidget({
        title: 'DynamoDB - Consumed Capacity',
        left: [
          this.customersTable.metricConsumedReadCapacityUnits({ period: cdk.Duration.minutes(1) }),
          this.customersTable.metricConsumedWriteCapacityUnits({ period: cdk.Duration.minutes(1) }),
        ],
        width: 12,
      }),
      new cloudwatch.GraphWidget({
        title: 'DynamoDB - Throttled Requests',
        left: [
          this.customersTable.metricThrottledRequestsForOperations({
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

    new cdk.CfnOutput(this, 'CrmApiUrl', {
      value: this.apiEndpoint,
      description: 'CRM API Gateway endpoint URL',
    });

    new cdk.CfnOutput(this, 'CustomersTableName', {
      value: this.customersTable.tableName,
      description: 'Customers DynamoDB table name',
    });

    new cdk.CfnOutput(this, 'CasesTableName', {
      value: this.casesTable.tableName,
      description: 'Cases DynamoDB table name',
    });

    new cdk.CfnOutput(this, 'InteractionsTableName', {
      value: this.interactionsTable.tableName,
      description: 'Interactions DynamoDB table name',
    });

    new cdk.CfnOutput(this, 'CrmDashboardUrl', {
      value: `https://${this.region}.console.aws.amazon.com/cloudwatch/home?region=${this.region}#dashboards:name=${resourcePrefix}-crm-dashboard`,
      description: 'CRM CloudWatch Dashboard URL',
    });
  }
}
