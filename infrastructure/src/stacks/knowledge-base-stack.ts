import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as path from 'path';
import { Construct } from 'constructs';
import { VoiceAgentConfig } from '../config';
import { SSM_PARAMS } from '../ssm-parameters';
import { KnowledgeBaseConstruct } from '../constructs';

/**
 * Props for KnowledgeBaseStack
 */
export interface KnowledgeBaseStackProps extends cdk.StackProps {
  readonly config: VoiceAgentConfig;
}

/**
 * Knowledge Base infrastructure stack for RAG (Retrieval-Augmented Generation).
 *
 * Creates:
 * - Bedrock Knowledge Base with S3 Vectors vector store
 * - S3 bucket for source documents
 * - IAM role for Bedrock to access resources
 * - Data source for automatic document sync
 *
 * Architecture:
 * - S3 Vectors is ~100x cheaper than OpenSearch Serverless
 * - Documents uploaded to S3 are automatically chunked and embedded
 * - ECS tasks query the Knowledge Base via bedrock-agent-runtime
 *
 * This is a standalone stack so it can be deployed independently from ECS,
 * allowing document updates without affecting compute resources.
 */
export class KnowledgeBaseStack extends cdk.Stack {
  /** Knowledge Base ID for queries */
  public readonly knowledgeBaseId: string;

  /** Knowledge Base ARN for IAM policies */
  public readonly knowledgeBaseArn: string;

  constructor(scope: Construct, id: string, props: KnowledgeBaseStackProps) {
    super(scope, id, props);

    const { config } = props;

    // =====================
    // Knowledge Base Construct
    // =====================
    const knowledgeBase = new KnowledgeBaseConstruct(this, 'KnowledgeBase', {
      environment: config.environment,
      projectName: config.projectName,
      region: this.region,
      account: this.account,
      documentsPath: path.join(__dirname, '..', '..', '..', 'resources', 'knowledge-base-documents'),
    });

    this.knowledgeBaseId = knowledgeBase.knowledgeBaseId;
    this.knowledgeBaseArn = knowledgeBase.knowledgeBaseArn;

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
      value: knowledgeBase.documentBucket.bucketName,
      description: 'S3 bucket for Knowledge Base documents',
    });
  }
}
