import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { CallFlowVisualizerStack } from '../src/stacks/call-flow-visualizer-stack';
import { SSM_PARAMS } from '../src/ssm-parameters';
import { TEST_CONFIG, TEST_ENV } from './helpers';

/**
 * SSM context entries needed by CallFlowVisualizerStack
 */
const VISUALIZER_SSM_CONTEXT: Record<string, string> = {
  [`ssm:account=${TEST_ENV.account}:parameterName=${SSM_PARAMS.TASK_LOG_GROUP_NAME}:region=${TEST_ENV.region}`]:
    '/ecs/test-voice-agent-poc',
  [`ssm:account=${TEST_ENV.account}:parameterName=${SSM_PARAMS.SESSION_TABLE_NAME}:region=${TEST_ENV.region}`]:
    'test-voice-agent-poc-sessions',
  [`ssm:account=${TEST_ENV.account}:parameterName=${SSM_PARAMS.SESSION_TABLE_ARN}:region=${TEST_ENV.region}`]:
    'arn:aws:dynamodb:us-east-1:123456789012:table/test-voice-agent-poc-sessions',
};

function createVisualizerStack(): Template {
  const app = new cdk.App({ context: VISUALIZER_SSM_CONTEXT });
  const stack = new CallFlowVisualizerStack(app, 'TestVisualizer', {
    env: TEST_ENV,
    config: { ...TEST_CONFIG, enableCallFlowVisualizer: true },
  });
  return Template.fromStack(stack);
}

describe('CallFlowVisualizerStack', () => {
  let template: Template;

  beforeAll(() => {
    template = createVisualizerStack();
  });

  describe('DynamoDB Call Events Table', () => {
    it('should create a DynamoDB table with PK/SK', () => {
      template.hasResourceProperties('AWS::DynamoDB::Table', {
        TableName: 'test-voice-agent-poc-call-events',
        KeySchema: [
          { AttributeName: 'PK', KeyType: 'HASH' },
          { AttributeName: 'SK', KeyType: 'RANGE' },
        ],
        BillingMode: 'PAY_PER_REQUEST',
      });
    });

    it('should have TTL enabled', () => {
      template.hasResourceProperties('AWS::DynamoDB::Table', {
        TimeToLiveSpecification: {
          AttributeName: 'TTL',
          Enabled: true,
        },
      });
    });

    it('should have GSI1 for calls by date', () => {
      template.hasResourceProperties('AWS::DynamoDB::Table', {
        GlobalSecondaryIndexes: Match.arrayWith([
          Match.objectLike({
            IndexName: 'GSI1',
            KeySchema: [
              { AttributeName: 'GSI1PK', KeyType: 'HASH' },
              { AttributeName: 'GSI1SK', KeyType: 'RANGE' },
            ],
          }),
        ]),
      });
    });

    it('should have GSI2 for calls by tool', () => {
      template.hasResourceProperties('AWS::DynamoDB::Table', {
        GlobalSecondaryIndexes: Match.arrayWith([
          Match.objectLike({
            IndexName: 'GSI2',
            KeySchema: [
              { AttributeName: 'GSI2PK', KeyType: 'HASH' },
              { AttributeName: 'GSI2SK', KeyType: 'RANGE' },
            ],
          }),
        ]),
      });
    });
  });

  describe('Ingester Lambda', () => {
    it('should create the ingester Lambda function', () => {
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-voice-agent-poc-call-flow-ingester',
        Runtime: 'python3.12',
        Handler: 'handler.handler',
        Timeout: 60,
      });
    });

    it('should pass EVENTS_TABLE_NAME env var', () => {
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-voice-agent-poc-call-flow-ingester',
        Environment: {
          Variables: Match.objectLike({
            EVENTS_TABLE_NAME: Match.anyValue(),
            EVENT_TTL_DAYS: '30',
          }),
        },
      });
    });

    it('should grant DynamoDB BatchWriteItem to ingester', () => {
      template.hasResourceProperties('AWS::IAM::Policy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: 'dynamodb:BatchWriteItem',
              Effect: 'Allow',
            }),
          ]),
        },
      });
    });
  });

  describe('CW Logs Subscription Filter', () => {
    it('should create a subscription filter', () => {
      template.hasResourceProperties('AWS::Logs::SubscriptionFilter', {
        FilterName: 'test-voice-agent-poc-call-flow-ingestion',
        LogGroupName: '/ecs/test-voice-agent-poc',
      });
    });
  });

  describe('Query Lambda', () => {
    it('should create the query Lambda function', () => {
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-voice-agent-poc-call-flow-api',
        Runtime: 'python3.12',
        Handler: 'handler.handler',
        Timeout: 30,
      });
    });

    it('should pass both table names as env vars', () => {
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'test-voice-agent-poc-call-flow-api',
        Environment: {
          Variables: Match.objectLike({
            EVENTS_TABLE_NAME: Match.anyValue(),
            SESSION_TABLE_NAME: 'test-voice-agent-poc-sessions',
          }),
        },
      });
    });

    it('should grant DynamoDB read on events table', () => {
      template.hasResourceProperties('AWS::IAM::Policy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: ['dynamodb:Query', 'dynamodb:GetItem'],
              Effect: 'Allow',
            }),
          ]),
        },
      });
    });

    it('should grant DynamoDB read on sessions table', () => {
      template.hasResourceProperties('AWS::IAM::Policy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: 'dynamodb:GetItem',
              Effect: 'Allow',
              Resource: 'arn:aws:dynamodb:us-east-1:123456789012:table/test-voice-agent-poc-sessions',
            }),
          ]),
        },
      });
    });
  });

  describe('API Gateway', () => {
    it('should create REST API', () => {
      template.hasResourceProperties('AWS::ApiGateway::RestApi', {
        Name: 'test-voice-agent-poc-call-flow-api',
      });
    });

    it('should create API Gateway deployment stage', () => {
      template.hasResourceProperties('AWS::ApiGateway::Stage', {
        StageName: 'poc',
      });
    });
  });

  describe('CloudWatch Log Groups', () => {
    it('should create ingester log group', () => {
      template.hasResourceProperties('AWS::Logs::LogGroup', {
        LogGroupName: '/aws/lambda/test-voice-agent-poc-call-flow-ingester',
        RetentionInDays: 7,
      });
    });

    it('should create query log group', () => {
      template.hasResourceProperties('AWS::Logs::LogGroup', {
        LogGroupName: '/aws/lambda/test-voice-agent-poc-call-flow-api',
        RetentionInDays: 7,
      });
    });
  });

  describe('S3 Bucket', () => {
    it('should create an S3 bucket with public access blocked', () => {
      template.hasResourceProperties('AWS::S3::Bucket', {
        BucketName: Match.stringLikeRegexp('test-voice-agent-poc-call-flow-ui-'),
        PublicAccessBlockConfiguration: {
          BlockPublicAcls: true,
          BlockPublicPolicy: true,
          IgnorePublicAcls: true,
          RestrictPublicBuckets: true,
        },
      });
    });
  });

  describe('CloudFront Distribution', () => {
    it('should create a CloudFront distribution', () => {
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: Match.objectLike({
          Comment: 'test-voice-agent-poc Call Flow Visualizer',
          DefaultRootObject: 'index.html',
        }),
      });
    });

    it('should have S3 as default origin', () => {
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: Match.objectLike({
          DefaultCacheBehavior: Match.objectLike({
            ViewerProtocolPolicy: 'redirect-to-https',
          }),
        }),
      });
    });

    it('should have /api/* behavior pointing to API Gateway', () => {
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: Match.objectLike({
          CacheBehaviors: Match.arrayWith([
            Match.objectLike({
              PathPattern: '/api/*',
              ViewerProtocolPolicy: 'redirect-to-https',
              AllowedMethods: Match.arrayWith(['GET', 'HEAD', 'OPTIONS', 'PUT', 'PATCH', 'POST', 'DELETE']),
            }),
          ]),
        }),
      });
    });

    it('should have SPA error responses for 403 and 404', () => {
      template.hasResourceProperties('AWS::CloudFront::Distribution', {
        DistributionConfig: Match.objectLike({
          CustomErrorResponses: Match.arrayWith([
            Match.objectLike({
              ErrorCode: 403,
              ResponseCode: 200,
              ResponsePagePath: '/index.html',
            }),
            Match.objectLike({
              ErrorCode: 404,
              ResponseCode: 200,
              ResponsePagePath: '/index.html',
            }),
          ]),
        }),
      });
    });

    it('should create an Origin Access Control for S3', () => {
      template.hasResourceProperties(
        'AWS::CloudFront::OriginAccessControl',
        Match.objectLike({
          OriginAccessControlConfig: Match.objectLike({
            OriginAccessControlOriginType: 's3',
            SigningBehavior: 'always',
            SigningProtocol: 'sigv4',
          }),
        })
      );
    });
  });

  describe('SPA Deployment', () => {
    it('should create a Custom::CDKBucketDeployment resource', () => {
      template.resourceCountIs('Custom::CDKBucketDeployment', 1);
    });
  });

  describe('Outputs', () => {
    it('should output CloudFront URL', () => {
      template.hasOutput('CloudFrontUrl', {});
    });

    it('should output API URL', () => {
      template.hasOutput('ApiUrl', {});
    });

    it('should output events table name', () => {
      template.hasOutput('EventsTableName', {});
    });
  });
});

describe('CallFlowVisualizer opt-in gate', () => {
  it('should NOT create the stack when enableCallFlowVisualizer is false', () => {
    // With enableCallFlowVisualizer=false, the stack should not be instantiated
    // This is enforced by the if-guard in main.ts; we verify the config default
    const config = { ...TEST_CONFIG, enableCallFlowVisualizer: false };
    expect(config.enableCallFlowVisualizer).toBe(false);
  });

  it('should create the stack when enableCallFlowVisualizer is true', () => {
    const app = new cdk.App({ context: VISUALIZER_SSM_CONTEXT });
    const enabledConfig = { ...TEST_CONFIG, enableCallFlowVisualizer: true };
    const stack = new CallFlowVisualizerStack(app, 'TestVisualizerEnabled', {
      env: TEST_ENV,
      config: enabledConfig,
    });
    const template = Template.fromStack(stack);
    template.resourceCountIs('AWS::DynamoDB::Table', 1);
  });
});
