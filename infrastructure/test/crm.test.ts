import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { CrmStack } from '../src/stacks/crm-stack';
import { SSM_PARAMS } from '../src/ssm-parameters';
import { TEST_CONFIG, TEST_ENV } from './helpers';

describe('CrmStack', () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new CrmStack(app, 'TestCrmStack', {
      env: TEST_ENV,
      config: TEST_CONFIG,
    });
    template = Template.fromStack(stack);
  });

  // --- DynamoDB Tables ---

  it('should create 3 DynamoDB tables', () => {
    template.resourceCountIs('AWS::DynamoDB::Table', 3);
  });

  it('should create Customers table with customer_id partition key', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TableName: Match.stringLikeRegexp('customers'),
      KeySchema: Match.arrayWith([
        Match.objectLike({ AttributeName: 'customer_id', KeyType: 'HASH' }),
      ]),
    });
  });

  it('should create Cases table with case_id partition key and customer_id sort key', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TableName: Match.stringLikeRegexp('cases'),
      KeySchema: Match.arrayWith([
        Match.objectLike({ AttributeName: 'case_id', KeyType: 'HASH' }),
        Match.objectLike({ AttributeName: 'customer_id', KeyType: 'RANGE' }),
      ]),
    });
  });

  it('should create Interactions table', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TableName: Match.stringLikeRegexp('interactions'),
      KeySchema: Match.arrayWith([
        Match.objectLike({ AttributeName: 'interaction_id', KeyType: 'HASH' }),
      ]),
    });
  });

  it('should create phone-index GSI on Customers table for phone lookups', () => {
    // Phone lookup is the primary CRM search method -- if this GSI is
    // missing, customer identification by caller ID fails.
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TableName: Match.stringLikeRegexp('customers'),
      GlobalSecondaryIndexes: Match.arrayWith([
        Match.objectLike({
          IndexName: 'phone-index',
          KeySchema: Match.arrayWith([
            Match.objectLike({ AttributeName: 'phone', KeyType: 'HASH' }),
          ]),
        }),
      ]),
    });
  });

  it('should create email-index GSI on Customers table', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TableName: Match.stringLikeRegexp('customers'),
      GlobalSecondaryIndexes: Match.arrayWith([
        Match.objectLike({
          IndexName: 'email-index',
          KeySchema: Match.arrayWith([
            Match.objectLike({ AttributeName: 'email', KeyType: 'HASH' }),
          ]),
        }),
      ]),
    });
  });

  it('should create customer-index GSI on Cases table', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TableName: Match.stringLikeRegexp('cases'),
      GlobalSecondaryIndexes: Match.arrayWith([
        Match.objectLike({ IndexName: 'customer-index' }),
      ]),
    });
  });

  it('should create status-index GSI on Cases table', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TableName: Match.stringLikeRegexp('cases'),
      GlobalSecondaryIndexes: Match.arrayWith([
        Match.objectLike({ IndexName: 'status-index' }),
      ]),
    });
  });

  it('should enable point-in-time recovery on all tables', () => {
    const tables = template.findResources('AWS::DynamoDB::Table');
    for (const [, table] of Object.entries(tables)) {
      expect(
        (table as any).Properties.PointInTimeRecoverySpecification?.PointInTimeRecoveryEnabled
      ).toBe(true);
    }
  });

  // --- Lambda ---

  it('should create CRM Lambda function', () => {
    template.hasResourceProperties('AWS::Lambda::Function', {
      Runtime: 'python3.11',
      Handler: 'index.handler',
    });
  });

  it('should pass DynamoDB table names as Lambda env vars', () => {
    // If these env vars don't match the actual table names,
    // every CRM API call fails with DynamoDB ValidationException.
    template.hasResourceProperties('AWS::Lambda::Function', {
      Environment: {
        Variables: Match.objectLike({
          CUSTOMERS_TABLE: Match.anyValue(),
          CASES_TABLE: Match.anyValue(),
          INTERACTIONS_TABLE: Match.anyValue(),
        }),
      },
    });
  });

  // --- API Gateway ---

  it('should create API Gateway REST API', () => {
    template.resourceCountIs('AWS::ApiGateway::RestApi', 1);
  });

  it('should create API endpoints for customers, cases, and interactions', () => {
    template.hasResourceProperties('AWS::ApiGateway::Resource', {
      PathPart: 'customers',
    });
    template.hasResourceProperties('AWS::ApiGateway::Resource', {
      PathPart: 'cases',
    });
    template.hasResourceProperties('AWS::ApiGateway::Resource', {
      PathPart: 'interactions',
    });
  });

  // --- SSM Parameters ---

  it('should create SSM parameter for CRM API URL', () => {
    // This SSM param is consumed by EcsStack and CrmAgentStack.
    // If the param name changes, both consumers silently get empty values.
    template.hasResourceProperties('AWS::SSM::Parameter', {
      Name: SSM_PARAMS.CRM_API_URL,
    });
  });

  it('should create SSM parameter for Customers table name', () => {
    template.hasResourceProperties('AWS::SSM::Parameter', {
      Name: SSM_PARAMS.CRM_CUSTOMERS_TABLE_NAME,
    });
  });

  it('should create SSM parameter for Cases table name', () => {
    template.hasResourceProperties('AWS::SSM::Parameter', {
      Name: SSM_PARAMS.CRM_CASES_TABLE_NAME,
    });
  });

  it('should create SSM parameter for Interactions table name', () => {
    template.hasResourceProperties('AWS::SSM::Parameter', {
      Name: SSM_PARAMS.CRM_INTERACTIONS_TABLE_NAME,
    });
  });

  // --- CloudWatch Alarms ---

  it('should create CloudWatch alarms for API errors', () => {
    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      AlarmName: Match.stringLikeRegexp('api-5xx-errors'),
    });
    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      AlarmName: Match.stringLikeRegexp('api-4xx-errors'),
    });
  });

  it('should create CloudWatch alarm for API latency', () => {
    template.hasResourceProperties('AWS::CloudWatch::Alarm', {
      AlarmName: Match.stringLikeRegexp('api-latency'),
    });
  });

  // --- Outputs ---

  it('should output CRM API URL', () => {
    template.hasOutput('CrmApiUrl', {});
  });

  it('should output table names', () => {
    template.hasOutput('CustomersTableName', {});
    template.hasOutput('CasesTableName', {});
    template.hasOutput('InteractionsTableName', {});
  });
});
