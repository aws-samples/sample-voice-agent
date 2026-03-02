import * as cdk from 'aws-cdk-lib';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as path from 'path';
import * as crypto from 'crypto';
import { Construct } from 'constructs';
import { SSM_PARAMS } from '../ssm-parameters';

/**
 * Props for KnowledgeBaseConstruct
 */
export interface KnowledgeBaseConstructProps {
  /**
   * Environment name (e.g., 'dev', 'staging', 'prod')
   */
  readonly environment: string;

  /**
   * Project name prefix for resources
   */
  readonly projectName: string;

  /**
   * AWS region for the Knowledge Base
   */
  readonly region: string;

  /**
   * AWS account ID
   */
  readonly account: string;

  /**
   * Optional path to directory containing documents to deploy
   * If provided, documents will be uploaded to the source bucket
   */
  readonly documentsPath?: string;

  /**
   * Name for the Knowledge Base (default: voice-agent-kb-{environment})
   */
  readonly knowledgeBaseName?: string;
}

/**
 * Creates a Bedrock Knowledge Base with S3 Vectors as the vector store.
 *
 * S3 Vectors is ~100x cheaper than OpenSearch Serverless:
 * - OpenSearch Serverless: ~$700/month (4 OCU minimum)
 * - S3 Vectors: ~$5/month (250K vectors)
 *
 * Architecture:
 * - S3 bucket for source documents
 * - S3 Vectors bucket for vector storage
 * - Bedrock Knowledge Base for RAG queries
 * - Custom Resource Lambda for lifecycle management
 *
 * The Custom Resource pattern is required because S3 Vectors doesn't have
 * native CloudFormation support yet (as of January 2025).
 */
export class KnowledgeBaseConstruct extends Construct {
  /** Knowledge Base ID for queries */
  public readonly knowledgeBaseId: string;

  /** Knowledge Base ARN for IAM policies */
  public readonly knowledgeBaseArn: string;

  /** S3 bucket for source documents */
  public readonly documentBucket: s3.Bucket;

  /** S3 Vectors bucket name */
  public readonly vectorBucketName: string;

  /** Data source ID */
  public readonly dataSourceId: string;

  constructor(scope: Construct, id: string, props: KnowledgeBaseConstructProps) {
    super(scope, id);

    const { environment, projectName, region, account } = props;
    const resourcePrefix = `${projectName}-${environment}`;
    const kbName = props.knowledgeBaseName ?? `${resourcePrefix}-kb`;
    const vectorBucketName = `${resourcePrefix}-vectors-${account}`;

    // =====================
    // S3 Bucket for Source Documents
    // =====================
    this.documentBucket = new s3.Bucket(this, 'DocumentBucket', {
      bucketName: `${resourcePrefix}-kb-documents-${account}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned: false,
    });

    this.vectorBucketName = vectorBucketName;

    // Deploy sample documents if path provided
    if (props.documentsPath) {
      new s3deploy.BucketDeployment(this, 'DocumentDeployment', {
        sources: [s3deploy.Source.asset(props.documentsPath)],
        destinationBucket: this.documentBucket,
        prune: false, // Don't delete existing documents
      });
    }

    // =====================
    // IAM Role for Bedrock Knowledge Base
    // =====================
    const bedrockRole = new iam.Role(this, 'BedrockKBRole', {
      assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com'),
      description: 'Role for Bedrock Knowledge Base to access S3 and S3 Vectors',
    });

    // S3 document bucket access
    bedrockRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'S3DocumentAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          's3:GetObject',
          's3:ListBucket',
        ],
        resources: [
          this.documentBucket.bucketArn,
          `${this.documentBucket.bucketArn}/*`,
        ],
      })
    );

    // S3 Vectors access - using correct ARN format (bucket/ not vector-bucket/)
    bedrockRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'S3VectorsAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          's3vectors:CreateIndex',
          's3vectors:DeleteIndex',
          's3vectors:GetIndex',
          's3vectors:ListIndexes',
          's3vectors:PutVectors',
          's3vectors:GetVectors',
          's3vectors:DeleteVectors',
          's3vectors:QueryVectors',
        ],
        resources: [
          `arn:aws:s3vectors:${region}:${account}:bucket/${vectorBucketName}`,
          `arn:aws:s3vectors:${region}:${account}:bucket/${vectorBucketName}/*`,
        ],
      })
    );

    // Bedrock embedding model access
    bedrockRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'BedrockEmbeddingAccess',
        effect: iam.Effect.ALLOW,
        actions: ['bedrock:InvokeModel'],
        resources: [
          `arn:aws:bedrock:${region}::foundation-model/amazon.titan-embed-text-v2:0`,
          // Also allow v1 model as fallback
          `arn:aws:bedrock:${region}::foundation-model/amazon.titan-embed-text-v1`,
        ],
      })
    );

    // =====================
    // Lambda for Custom Resource
    // =====================
    const kbLogGroup = new logs.LogGroup(this, 'KBManagementLogGroup', {
      logGroupName: `/aws/lambda/${resourcePrefix}-kb-management`,
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const kbManagementLambda = new lambda.Function(this, 'KBManagementFunction', {
      functionName: `${resourcePrefix}-kb-management`,
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromAsset(
        path.join(__dirname, '..', 'lambdas', 'knowledgeBase')
      ),
      timeout: cdk.Duration.minutes(10), // KB creation can take a while
      memorySize: 256,
      logGroup: kbLogGroup,
    });

    // Lambda permissions for S3 Vectors management
    kbManagementLambda.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'S3VectorsManagement',
        effect: iam.Effect.ALLOW,
        actions: [
          's3vectors:CreateVectorBucket',
          's3vectors:DeleteVectorBucket',
          's3vectors:GetVectorBucket',
          's3vectors:ListVectorBuckets',
          's3vectors:CreateIndex',
          's3vectors:DeleteIndex',
          's3vectors:GetIndex',
          's3vectors:ListIndexes',
        ],
        resources: ['*'], // S3 Vectors requires * for bucket-level operations
      })
    );

    // Lambda permissions for Bedrock Knowledge Base management
    kbManagementLambda.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'BedrockKBManagement',
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock:CreateKnowledgeBase',
          'bedrock:DeleteKnowledgeBase',
          'bedrock:GetKnowledgeBase',
          'bedrock:UpdateKnowledgeBase',
          'bedrock:ListKnowledgeBases',
          'bedrock:CreateDataSource',
          'bedrock:DeleteDataSource',
          'bedrock:GetDataSource',
          'bedrock:UpdateDataSource',
          'bedrock:ListDataSources',
          'bedrock:StartIngestionJob',
          'bedrock:GetIngestionJob',
          'bedrock:ListIngestionJobs',
        ],
        resources: ['*'], // KB operations require *
      })
    );

    // Allow Lambda to pass the Bedrock role
    kbManagementLambda.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'PassBedrockRole',
        effect: iam.Effect.ALLOW,
        actions: ['iam:PassRole'],
        resources: [bedrockRole.roleArn],
        conditions: {
          StringEquals: {
            'iam:PassedToService': 'bedrock.amazonaws.com',
          },
        },
      })
    );

    // =====================
    // Custom Resource Provider
    // =====================
    // Create explicit log group for Custom Resource Provider (avoids deprecated logRetention)
    const providerLogGroup = new logs.LogGroup(this, 'KnowledgeBaseProviderLogGroup', {
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const provider = new cr.Provider(this, 'KnowledgeBaseProvider', {
      onEventHandler: kbManagementLambda,
      logGroup: providerLogGroup,
    });

    // Generate config hash for change detection
    const configString = JSON.stringify({
      vectorBucketName,
      kbName,
      documentBucketArn: this.documentBucket.bucketArn,
      embeddingModelArn: `arn:aws:bedrock:${region}::foundation-model/amazon.titan-embed-text-v2:0`,
    });
    const configHash = crypto
      .createHash('sha256')
      .update(configString)
      .digest('hex')
      .substring(0, 16);

    // =====================
    // Custom Resource
    // =====================
    const knowledgeBaseResource = new cdk.CustomResource(this, 'KnowledgeBaseResource', {
      serviceToken: provider.serviceToken,
      properties: {
        VectorBucketName: vectorBucketName,
        KnowledgeBaseName: kbName,
        DocumentBucketArn: this.documentBucket.bucketArn,
        DocumentBucketName: this.documentBucket.bucketName,
        BedrockRoleArn: bedrockRole.roleArn,
        EmbeddingModelArn: `arn:aws:bedrock:${region}::foundation-model/amazon.titan-embed-text-v2:0`,
        ConfigHash: configHash,
      },
    });

    // Ensure role exists before creating KB
    knowledgeBaseResource.node.addDependency(bedrockRole);
    knowledgeBaseResource.node.addDependency(this.documentBucket);

    // Extract outputs from Custom Resource
    this.knowledgeBaseId = knowledgeBaseResource.getAttString('KnowledgeBaseId');
    this.knowledgeBaseArn = knowledgeBaseResource.getAttString('KnowledgeBaseArn');
    this.dataSourceId = knowledgeBaseResource.getAttString('DataSourceId');

    // =====================
    // SSM Parameters
    // =====================
    new ssm.StringParameter(this, 'KnowledgeBaseIdParam', {
      parameterName: SSM_PARAMS.KNOWLEDGE_BASE_ID,
      stringValue: this.knowledgeBaseId,
      description: 'Voice Agent Bedrock Knowledge Base ID',
    });

    new ssm.StringParameter(this, 'KnowledgeBaseArnParam', {
      parameterName: SSM_PARAMS.KNOWLEDGE_BASE_ARN,
      stringValue: this.knowledgeBaseArn,
      description: 'Voice Agent Bedrock Knowledge Base ARN',
    });

    new ssm.StringParameter(this, 'KnowledgeBaseBucketParam', {
      parameterName: SSM_PARAMS.KNOWLEDGE_BASE_BUCKET,
      stringValue: this.documentBucket.bucketName,
      description: 'Voice Agent Knowledge Base Document Bucket Name',
    });

    // =====================
    // Outputs
    // =====================
    new cdk.CfnOutput(this, 'KnowledgeBaseId', {
      value: this.knowledgeBaseId,
      description: 'Bedrock Knowledge Base ID',
    });

    new cdk.CfnOutput(this, 'KnowledgeBaseArn', {
      value: this.knowledgeBaseArn,
      description: 'Bedrock Knowledge Base ARN',
    });

    new cdk.CfnOutput(this, 'DocumentBucketName', {
      value: this.documentBucket.bucketName,
      description: 'S3 bucket for Knowledge Base documents',
    });

    new cdk.CfnOutput(this, 'VectorBucketName', {
      value: vectorBucketName,
      description: 'S3 Vectors bucket name',
    });

    new cdk.CfnOutput(this, 'DataSourceId', {
      value: this.dataSourceId,
      description: 'Bedrock Data Source ID',
    });
  }
}
