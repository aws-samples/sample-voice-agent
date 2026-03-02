# CDK Standard Template


This document defines our standard patterns for AWS CDK projects based on proven production patterns. Use this as a reference when building new CDK infrastructure.

---

## Table of Contents

0. [AWS Credentials for CDK](#0-aws-credentials-for-cdk)
1. [Project Structure](#1-project-structure)
2. [Resource Naming Best Practices](#2-resource-naming-best-practices)
3. [Stack Patterns](#3-stack-patterns)
4. [Construct Patterns](#4-construct-patterns)
5. [Configuration Management](#5-configuration-management)
6. [Lambda Resources](#6-lambda-resources)
7. [Deployment Patterns](#7-deployment-patterns)
8. [Security Best Practices](#8-security-best-practices)
9. [Frontend Integration](#9-frontend-integration)
10. [TypeScript Configuration](#10-typescript-configuration)
11. [Quick Start Checklist](#11-quick-start-checklist)

---

## 0. AWS Credentials for CDK

### Required Permissions for CDK Synth

**IMPORTANT**: CDK requires AWS credentials **even for `cdk synth`** because it performs lookups during synthesis.

### Minimum Required Permissions

For `cdk synth` to work properly, your AWS credentials need these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeAvailabilityZones",
        "ec2:DescribeVpcs",
        "ec2:DescribeSubnets",
        "ec2:DescribeRouteTables",
        "ssm:GetParameter"
      ],
      "Resource": "*"
    }
  ]
}
```

**Why These Permissions?**
- **ec2:DescribeAvailabilityZones**: VPC construct looks up available AZs in the region
- **ec2:Describe\***: VPC construct validates existing network resources
- **ssm:GetParameter**: Reading CDK context values from SSM Parameter Store

### ❌ DON'T: Hardcode Availability Zones in cdk.json

**Bad Pattern (Avoid This):**
```json
// cdk.json
{
  "context": {
    "availability-zones:account=123456789012:region=us-east-1": [
      "us-east-1a",
      "us-east-1b"
    ]
  }
}
```

**Why This is Bad:**
- ❌ Hardcoded data that becomes outdated
- ❌ Doesn't work across regions or accounts
- ❌ Hides permission issues instead of fixing them
- ❌ Requires manual updates when AZs change

### ⚠️ IMPORTANT: Add cdk.context.json to .gitignore

**CDK automatically creates `cdk.context.json`** when it performs lookups (availability zones, AMIs, etc.). This file contains account-specific and region-specific cached data.

**You MUST add it to .gitignore:**
```gitignore
# infrastructure/.gitignore
*.js
!jest.config.js
*.d.ts
node_modules

# CDK asset staging directory
.cdk.staging
cdk.out
cdk.context.json  # ⚠️ IMPORTANT: Add this line

# Build artifacts
dist/

# Environment variables
.env
```

**Why:**
- ❌ Contains hardcoded account/region-specific data
- ❌ Doesn't work when deployed to different accounts/regions
- ❌ Creates merge conflicts in team environments
- ✅ CDK will regenerate it automatically with proper credentials
- ✅ Each developer/environment should have their own context based on their AWS credentials

### ✅ DO: Use Proper AWS Credentials

**Good Pattern:**
1. Ensure AWS credentials have proper permissions
2. Let CDK look up availability zones dynamically
3. No hardcoded data in cdk.json

**Setting Up Credentials:**

```bash
# Option 1: AWS CLI (recommended for development)
aws configure
# Enter your access key, secret key, region

# Option 2: Environment variables
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
export AWS_REGION=us-east-1

# Option 3: AWS SSO (recommended for organizations)
aws sso login --profile your-profile
export AWS_PROFILE=your-profile

# Verify credentials work
aws sts get-caller-identity
aws ec2 describe-availability-zones --region us-east-1
```

### Credential Requirements by CDK Command

| Command | AWS API Calls | Required Permissions |
|---------|---------------|---------------------|
| `cdk synth` | ✅ Yes (lookups) | Read-only (ec2:Describe*, ssm:GetParameter) |
| `cdk diff` | ✅ Yes (reads CloudFormation) | Read-only + cloudformation:DescribeStacks |
| `cdk deploy` | ✅ Yes (creates resources) | Full deployment permissions |
| `cdk destroy` | ✅ Yes (deletes resources) | Full deployment permissions |

### Troubleshooting Permission Issues

**Error: "not authorized to perform: ec2:DescribeAvailabilityZones"**

❌ **Bad Fix**: Hardcode AZs in cdk.json
✅ **Good Fix**: Add `ec2:DescribeAvailabilityZones` permission to your IAM role/user

**Steps to Fix:**
1. Identify your IAM user/role:
   ```bash
   aws sts get-caller-identity
   ```

2. Attach a policy with required permissions (see above)

3. Verify the fix:
   ```bash
   aws ec2 describe-availability-zones
   ```

4. Run `cdk synth` again

### Simplicity Over Optimization

**RULE**: Don't overcomplicate infrastructure for cost optimization during development.

❌ **Bad Pattern (Overcomplicating):**
```typescript
// Don't do this - it adds complexity without value during development
natGateways: props.environment === 'prod' ? 2 : 1,
```

✅ **Good Pattern (Keep it Simple):**
```typescript
// Always use 2 NAT Gateways for high availability
natGateways: 2,
```

**Why Simplicity Matters:**
- Development time is more expensive than infrastructure costs
- Complexity adds cognitive load and maintenance burden
- Cost optimization should happen AFTER you have a working system
- Premature optimization is the root of all evil

**When to Optimize:**
- ✅ After the system is working
- ✅ When you have actual cost data showing a problem
- ✅ When scaling to production workloads
- ❌ During initial development
- ❌ Without measuring actual costs first

---

## 1. Project Structure

### Directory Organization

```
project-root/
├── infrastructure/          # CDK infrastructure code
│   ├── src/                # TypeScript source files
│   │   ├── main.ts        # CDK app entry point
│   │   ├── stacks/        # Stack definitions
│   │   ├── constructs/    # Reusable constructs
│   │   ├── lambda-edge/   # Lambda@Edge functions (if needed)
│   │   └── functions/     # Standard Lambda functions
│   ├── dist/              # Compiled JavaScript (gitignored)
│   ├── cdk.out/           # CDK CloudFormation output (gitignored)
│   ├── cdk.json           # CDK configuration
│   ├── tsconfig.json      # TypeScript configuration
│   ├── package.json       # Dependencies and scripts
│   ├── .env.example       # Example environment variables
│   └── deploy.sh          # Deployment orchestration script
├── backend/               # Backend services/containers
├── frontend/              # Frontend application (if applicable)
├── docs/                  # Documentation
├── .gitignore             # Git ignore rules
└── package.json           # Workspace root (optional)
```

### Key Principles

**1. Separate Source from Build Artifacts**
- Source code: `infrastructure/src/`
- Compiled code: `infrastructure/dist/` (gitignored)
- CDK output: `infrastructure/cdk.out/` (gitignored)

**WHY**: Build artifacts can be regenerated. Version control should only track source code. This follows CDK best practices and makes .gitignore clean.

**2. Monorepo with Workspace (Optional)**
If you have multiple packages (infra + frontend + services):

```json
// Root package.json
{
  "private": true,
  "workspaces": ["infrastructure", "frontend", "backend/*"],
  "scripts": {
    "lint": "eslint . --ext .js,.jsx,.ts,.tsx",
    "format": "prettier --write ."
  }
}
```

**WHY**: Shared tooling (ESLint, Prettier, Husky) at workspace level. Dependencies isolated per package.

---

## 2. Resource Naming Best Practices

### ⚠️ CRITICAL: Avoid Explicit Resource Names

**RULE**: Only name resources when absolutely necessary (e.g., domain names, cross-stack references that must be stable).

### Why Avoid Naming?

1. **Update Flexibility**: CloudFormation cannot rename resources. If you change a name, CloudFormation must delete and recreate the resource, causing data loss.

2. **Multi-Environment Support**: Named resources can collide across environments in the same account.

3. **Stack Replacement**: Named resources prevent CloudFormation from replacing stacks cleanly.

4. **Circular Dependencies**: Named resources can create hard dependencies that complicate deployments.

5. **Account Migration**: Moving stacks between accounts becomes difficult with hardcoded names.

### Pattern: Let CloudFormation Generate Names

```typescript
// ❌ BAD - Explicit naming causes issues
const bucket = new s3.Bucket(this, 'ResultsBucket', {
  bucketName: `${projectName}-results-${props.environment}-${this.account}`,
  // ... other props
});

// ✅ GOOD - CloudFormation generates unique name
const bucket = new s3.Bucket(this, 'ResultsBucket', {
  // No bucketName property!
  // CloudFormation generates: stackname-resultsbucket-abc123xyz
  // ... other props
});
```

### Finding Resources: Use Tags and Outputs

**Instead of hardcoded names, use:**

1. **CloudFormation Outputs** to export resource identifiers:
```typescript
new CfnOutput(this, 'ResultsBucketName', {
  value: bucket.bucketName,
  description: 'S3 bucket for validation results',
  exportName: `${id}-ResultsBucketName`,
});
```

2. **Resource Tags** for identification:
```typescript
Tags.of(bucket).add('Purpose', 'ValidationResults');
Tags.of(bucket).add('Environment', props.environment);
Tags.of(bucket).add('Project', 'aws-sample-validation');
```

3. **AWS Resource Groups** to query by tags:
```bash
aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=Purpose,Values=ValidationResults \
  --resource-type-filters s3:bucket
```

### When Naming IS Required

Some resources MUST be named:

```typescript
// ✅ Domain names (must be explicit)
const certificate = new acm.Certificate(this, 'Certificate', {
  domainName: 'example.com',  // Required
  validation: acm.CertificateValidation.fromDns(hostedZone),
});

// ✅ SSM parameters (must be explicit for cross-stack references)
new ssm.StringParameter(this, 'ApiEndpoint', {
  parameterName: `/my-app/${props.environment}/api-endpoint`,
  stringValue: api.url,
});

// ❌ S3 buckets (let CloudFormation name them)
const bucket = new s3.Bucket(this, 'Bucket');  // No bucketName!

// ❌ DynamoDB tables (let CloudFormation name them)
const table = new dynamodb.Table(this, 'Table', {
  partitionKey: { name: 'id', type: dynamodb.AttributeType.STRING },
  // No tableName!
});

// ❌ Lambda functions (let CloudFormation name them)
const fn = new lambda.Function(this, 'Handler', {
  runtime: lambda.Runtime.NODEJS_18_X,
  handler: 'index.handler',
  code: lambda.Code.fromAsset('lambda'),
  // No functionName!
});
```

### Exception: When You Need Stable Names

If you absolutely need stable names (not recommended), use this pattern:

```typescript
// Only if you have a compelling reason
const table = new dynamodb.Table(this, 'MetadataTable', {
  tableName: props.tableName,  // From props, not hardcoded
  partitionKey: { name: 'id', type: dynamodb.AttributeType.STRING },
  removalPolicy: RemovalPolicy.RETAIN,  // CRITICAL: prevent deletion
});
```

**IMPORTANT**: If you name a resource, you MUST use `RemovalPolicy.RETAIN` for production to prevent accidental data loss during stack updates.

### Pattern: Referencing Resources Across Stacks

**Use direct references (dependency injection), not names:**

```typescript
// Stack 1: Create resource
export class DataStack extends Stack {
  public readonly table: dynamodb.ITable;

  constructor(scope: Construct, id: string, props: StackProps) {
    super(scope, id, props);
    this.table = new dynamodb.Table(this, 'Table', {
      partitionKey: { name: 'id', type: dynamodb.AttributeType.STRING },
      // No tableName!
    });
  }
}

// Stack 2: Reference resource
export class ApiStack extends Stack {
  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    // ✅ Direct reference via props
    const fn = new lambda.Function(this, 'ApiHandler', {
      // ...
      environment: {
        TABLE_NAME: props.table.tableName,  // Use the actual resource
      },
    });

    props.table.grantReadWriteData(fn);  // Grants work correctly
  }
}

// main.ts
const dataStack = new DataStack(app, 'DataStack', { env });
const apiStack = new ApiStack(app, 'ApiStack', {
  env,
  table: dataStack.table,  // Pass the actual resource
});
```

### Summary: Naming Decision Tree

```
Do you need to name this resource?
│
├─ Is it a domain name? ──────────────────────────► YES, name it
│
├─ Is it an SSM parameter for cross-stack refs? ──► YES, name it
│
├─ Is it a resource that must be accessed from ───► Maybe - consider using
│  outside CloudFormation (e.g., GitHub Actions)?    SSM Parameter Store instead
│
└─ Everything else ────────────────────────────────► NO, let CloudFormation name it
```

**WHY**:
- CloudFormation-generated names are unique and prevent conflicts
- Stack updates and replacements work smoothly
- No risk of name collisions across environments
- Resources can be renamed without data loss
- Simpler code with fewer hardcoded values
- Better alignment with CloudFormation best practices

---

## 3. Stack Patterns

### Thin Stack as Orchestrator

**Pattern**: Stacks should be thin wrappers that orchestrate constructs.

```typescript
// infrastructure/src/stacks/website-stack.ts
import { Stack, StackProps, CfnOutput } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { WebsiteConstruct } from '../constructs/website-construct';

export interface WebsiteStackProps extends StackProps {
  environment: 'dev' | 'staging' | 'prod';
  domainName: string;
  hostedZoneId: string;
  hostedZoneName: string;
}

export class WebsiteStack extends Stack {
  constructor(scope: Construct, id: string, props: WebsiteStackProps) {
    super(scope, id, props);

    // Delegate to construct (business logic lives there)
    const website = new WebsiteConstruct(this, 'Website', {
      environment: props.environment,
      domainName: props.domainName,
      hostedZoneId: props.hostedZoneId,
      hostedZoneName: props.hostedZoneName,
    });

    // Stack only handles CloudFormation outputs
    new CfnOutput(this, 'DomainName', {
      value: `https://${website.domainName}`,
      description: 'Website URL',
      exportName: `${id}-DomainName`,
    });

    new CfnOutput(this, 'DistributionId', {
      value: website.distribution.distributionId,
      description: 'CloudFront Distribution ID',
    });
  }
}
```

**WHY**:
- Stack remains focused on orchestration
- Business logic in constructs (reusable across projects)
- Easier to test constructs in isolation
- Single responsibility principle

### When to Split into Multiple Stacks

**Split stacks when**:
1. **Circular dependencies exist** (e.g., Cognito needs app URL, app needs Cognito config)
2. **Different update cadences** (e.g., networking changes rarely, app changes frequently)
3. **Resource limits** (CloudFormation has 500 resource limit per stack)
4. **Manual steps required between deployments** (e.g., external system configuration)

**Example: Three-Stack Pattern**
```typescript
// main.ts
const app = new App();

// Stack 1: Foundation (VPC, networking)
const networkStack = new NetworkStack(app, 'Network', { env });

// Stack 2: Data layer (databases)
const dataStack = new DataStack(app, 'Data', {
  env,
  vpc: networkStack.vpc,
});

// Stack 3: Application
const appStack = new ApplicationStack(app, 'App', {
  env,
  vpc: networkStack.vpc,
  database: dataStack.database,
});
```

### SSM Parameter Store for Cross-Stack Communication

**Pattern**: Use SSM Parameter Store instead of CloudFormation exports to avoid hard dependencies.

```typescript
// Stack 1: Export values to SSM
import { StringParameter } from 'aws-cdk-lib/aws-ssm';

const ssmPrefix = `/${props.environment}/${projectName}`;

new StringParameter(this, 'VpcIdParam', {
  parameterName: `${ssmPrefix}/vpc/id`,
  stringValue: vpc.vpcId,
  description: `VPC ID for ${props.environment}`,
});

new StringParameter(this, 'DatabaseEndpointParam', {
  parameterName: `${ssmPrefix}/database/endpoint`,
  stringValue: database.clusterEndpoint.hostname,
  description: `Database endpoint for ${props.environment}`,
});
```

```typescript
// Stack 2: Import values from SSM
import { StringParameter } from 'aws-cdk-lib/aws-ssm';

const ssmPrefix = `/${props.environment}/${projectName}`;

const vpcId = StringParameter.valueForStringParameter(
  this,
  `${ssmPrefix}/vpc/id`
);

const databaseEndpoint = StringParameter.valueForStringParameter(
  this,
  `${ssmPrefix}/database/endpoint`
);
```

**WHY**:
- No hard CloudFormation dependencies (stacks can be updated independently)
- Stacks can be deleted without dependency conflicts
- Works across regions
- Can be read by any service (not just CloudFormation)
- Cleaner separation of concerns

**When to use CloudFormation Exports vs SSM Parameters:**

| Feature | CloudFormation Exports | SSM Parameters |
|---------|----------------------|----------------|
| **Cross-stack dependencies** | Hard (blocks stack deletion) | Soft (no blocking) |
| **Cross-region** | ❌ No (same region only) | ✅ Yes |
| **External access** | ❌ No (CloudFormation only) | ✅ Yes (any AWS service) |
| **Update flexibility** | ❌ Can't update if imported | ✅ Update anytime |
| **Stack deletion** | ❌ Blocked by importing stacks | ✅ Independent deletion |
| **Best for** | Internal stack outputs | Cross-stack communication |

**Recommendation:** Prefer SSM Parameters for cross-stack communication. Only use CloudFormation exports (`exportName`) for values that truly must be exported for external CloudFormation templates.

**Example: Using SSM for External Access**
```typescript
// Write to SSM in your stack
new StringParameter(this, 'StateMachineArnParam', {
  parameterName: `/aws-sample-validation/${props.environment}/state-machine-arn`,
  stringValue: stateMachine.stateMachineArn,
  description: 'ARN for triggering validations',
});

// External systems can read via AWS SDK
const ssm = new AWS.SSM();
const param = await ssm.getParameter({
  Name: '/aws-sample-validation/prod/state-machine-arn'
}).promise();
const stateMachineArn = param.Parameter.Value;
```


### Stack Props and Dependency Injection

```typescript
export interface ApplicationStackProps extends StackProps {
  // Environment (required)
  environment: 'dev' | 'staging' | 'prod';

  // External resources (dependency injection)
  vpc: ec2.IVpc;
  database: rds.IDatabaseCluster;

  // Configuration
  domainName: string;
  certificateArn: string;
}
```

**WHY**:
- Type-safe prop interfaces
- Explicit dependencies
- Environment union types prevent typos
- Self-documenting code

---

## 3. Construct Patterns

### Construct as Reusable Business Logic

**Pattern**: Constructs encapsulate complete infrastructure patterns.

```typescript
// infrastructure/src/constructs/api-construct.ts
import { Construct } from 'constructs';
import { Duration, RemovalPolicy } from 'aws-cdk-lib';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as logs from 'aws-cdk-lib/aws-logs';

export interface ApiConstructProps {
  environment: 'dev' | 'staging' | 'prod';
  vpc: ec2.IVpc;
  database: rds.IDatabaseCluster;
}

export class ApiConstruct extends Construct {
  public readonly api: apigateway.RestApi;
  public readonly apiUrl: string;

  constructor(scope: Construct, id: string, props: ApiConstructProps) {
    super(scope, id);

    // Create Lambda function
    const apiFunction = new lambda.Function(this, 'ApiFunction', {
      runtime: lambda.Runtime.NODEJS_18_X,
      handler: 'index.handler',
      code: lambda.Code.fromAsset('dist/api'),
      vpc: props.vpc,
      environment: {
        DATABASE_ENDPOINT: props.database.clusterEndpoint.hostname,
        ENVIRONMENT: props.environment,
      },
      timeout: Duration.seconds(30),
      memorySize: 1024,
      logRetention: props.environment === 'prod'
        ? logs.RetentionDays.ONE_MONTH
        : logs.RetentionDays.ONE_WEEK,
    });

    // Grant database access
    props.database.grantConnect(apiFunction);

    // Create API Gateway
    this.api = new apigateway.RestApi(this, 'Api', {
      restApiName: `${id}-${props.environment}`,
      deployOptions: {
        stageName: props.environment,
        loggingLevel: apigateway.MethodLoggingLevel.INFO,
        dataTraceEnabled: props.environment !== 'prod',
      },
    });

    // Add integration
    const integration = new apigateway.LambdaIntegration(apiFunction);
    this.api.root.addProxy({
      defaultIntegration: integration,
    });

    this.apiUrl = this.api.url;
  }
}
```

**WHY**:
- Complete infrastructure pattern in one reusable unit
- Exposes resources via public properties
- Self-contained with all necessary configurations
- Can be tested independently

### Environment-Aware Removal Policies

**Pattern**: Production resources should be protected from accidental deletion.

```typescript
const bucket = new s3.Bucket(this, 'DataBucket', {
  bucketName: `${projectName}-${props.environment}-data`,
  blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,

  // Environment-aware policies
  removalPolicy: props.environment === 'prod'
    ? RemovalPolicy.RETAIN
    : RemovalPolicy.DESTROY,

  autoDeleteObjects: props.environment !== 'prod',

  // Environment-specific lifecycle rules
  lifecycleRules: props.environment === 'prod' ? [
    {
      transitions: [
        {
          storageClass: s3.StorageClass.INTELLIGENT_TIERING,
          transitionAfter: Duration.days(90),
        },
      ],
    },
  ] : [],
});
```

**WHY**:
- Production data protected (RETAIN policy)
- Dev/staging can be cleaned up automatically (reduces costs)
- Prevents CloudFormation stack deletion failures
- Different lifecycle policies for different environments


### Constructor Validation

**Pattern**: Validate props in constructor with helpful error messages.

```typescript
export class ApiConstruct extends Construct {
  constructor(scope: Construct, id: string, props: ApiConstructProps) {
    super(scope, id);

    // Validate required props
    if (!props.vpc) {
      throw new Error(`${id}: vpc is required in props`);
    }

    if (!props.database) {
      throw new Error(`${id}: database is required in props`);
    }

    // Validate environment
    const validEnvironments = ['dev', 'staging', 'prod'];
    if (!validEnvironments.includes(props.environment)) {
      throw new Error(
        `${id}: environment must be one of: ${validEnvironments.join(', ')}`
      );
    }

    // Continue with construct creation...
  }
}
```

**WHY**:
- Fail fast with clear error messages
- Errors caught during synth (before deployment)
- Prevents partial/broken deployments
- Self-documenting requirements

---

## 4. Configuration Management

### .env File Structure

**Pattern**: Use .env files for configuration, never commit secrets.

```bash
# infrastructure/.env.example

# ===================================
# Environment Configuration
# ===================================
ENVIRONMENT=dev

# ===================================
# AWS Configuration
# ===================================
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=123456789012

# ===================================
# Domain Configuration
# ===================================
DOMAIN_NAME=example.com
HOSTED_ZONE_ID=Z1234567890ABC
HOSTED_ZONE_NAME=example.com

# ===================================
# External Service Configuration
# ===================================
# These require manual setup - see docs/SETUP.md
EXTERNAL_API_KEY=PLACEHOLDER_KEY
EXTERNAL_CLIENT_SECRET=PLACEHOLDER_SECRET

# ===================================
# Deployment Options
# ===================================
SKIP_FRONTEND_BUILD=false
REQUIRE_APPROVAL=false
```

**Loading in main.ts**:
```typescript
import * as dotenv from 'dotenv';
import * as path from 'path';
import { App } from 'aws-cdk-lib';

// Load environment variables from .env file
dotenv.config({ path: path.join(__dirname, '..', '.env') });

const app = new App();

// Get configuration with fallbacks
const envKey = app.node.tryGetContext('environment')
  || process.env.ENVIRONMENT
  || 'dev';

const awsRegion = process.env.AWS_REGION
  || process.env.CDK_DEFAULT_REGION
  || 'us-east-1';

const awsAccount = process.env.AWS_ACCOUNT_ID
  || process.env.CDK_DEFAULT_ACCOUNT;

// Validate required configuration
if (!awsAccount) {
  throw new Error('AWS_ACCOUNT_ID must be set in .env or CDK_DEFAULT_ACCOUNT');
}

const domainName = process.env.DOMAIN_NAME;
if (!domainName) {
  throw new Error('DOMAIN_NAME must be set in .env');
}
```

**WHY**:
- Secrets never committed (`.env` in .gitignore)
- `.env.example` documents required variables
- Fallbacks provide sensible defaults
- CDK context can override environment variables
- Validates at synth time (fails fast)


### Build-Time vs Runtime Configuration

**Build-Time** (baked into code):
- Best for: Immutable infrastructure configuration
- When: Lambda@Edge, constants, regions
- How: esbuild `define` option

```typescript
bundling: {
  define: {
    'API_ENDPOINT': JSON.stringify(apiEndpoint),
    'REGION': JSON.stringify(region),
  },
}
```

**Runtime** (environment variables):
- Best for: Dynamic configuration, secrets from Secrets Manager
- When: Standard Lambda, ECS, services that support env vars
- How: Lambda environment property

```typescript
environment: {
  DATABASE_ENDPOINT: database.clusterEndpoint.hostname,
  SECRETS_ARN: secret.secretArn,
}
```

**Runtime API-Based** (fetch from service):
- Best for: Frontend configuration, user-specific config
- When: Browser apps, mobile apps
- How: API endpoint that returns config

**WHY**: Right tool for the right job. Lambda@Edge has size limits (build-time). Standard services benefit from runtime flexibility.

---

## 5. Lambda Resources

### Self-Contained Lambda Organization

**Pattern**: Each Lambda function is self-contained with its own package.json.

```
infrastructure/src/
├── functions/
│   ├── api-handler/
│   │   ├── index.ts          # Handler code
│   │   ├── package.json      # Function-specific dependencies
│   │   ├── business-logic.ts # Supporting files
│   │   └── types.ts
│   ├── data-processor/
│   │   ├── index.ts
│   │   ├── package.json
│   │   └── processor.ts
│   └── scheduled-task/
│       ├── index.ts
│       └── package.json
└── lambda-edge/              # Special: us-east-1 only
    ├── viewer-request/
    │   ├── index.ts
    │   └── package.json
    └── origin-response/
        ├── index.ts
        └── package.json
```

**WHY**:
- Clear boundaries between functions
- Each function has only the dependencies it needs (smaller bundles)
- Easy to understand function scope
- Can be developed and tested independently

### Lambda Construct with Bundling

**Pattern**: Use NodejsFunction for automatic bundling.

```typescript
import { NodejsFunction } from 'aws-cdk-lib/aws-lambda-nodejs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as path from 'path';

const apiFunction = new NodejsFunction(this, 'ApiFunction', {
  entry: path.join(__dirname, '../functions/api-handler/index.ts'),
  handler: 'handler',
  runtime: lambda.Runtime.NODEJS_18_X,

  // Bundling configuration
  bundling: {
    minify: true,
    sourceMap: true,  // Enable for debugging
    target: 'es2020',
    externalModules: [
      'aws-sdk',  // Provided by Lambda runtime
      '@aws-sdk/client-*',  // v3 SDK provided
    ],

    // Build-time constants
    define: {
      'process.env.API_VERSION': JSON.stringify('1.0.0'),
    },

    // Additional esbuild options
    loader: {
      '.graphql': 'text',
      '.sql': 'text',
    },
  },

  // Runtime configuration
  environment: {
    NODE_OPTIONS: '--enable-source-maps',
    DATABASE_ENDPOINT: props.database.clusterEndpoint.hostname,
  },

  timeout: Duration.seconds(30),
  memorySize: 1024,

  // Environment-aware settings
  logRetention: props.environment === 'prod'
    ? logs.RetentionDays.ONE_MONTH
    : logs.RetentionDays.ONE_WEEK,
});
```

**WHY**:
- Automatic TypeScript compilation and bundling
- esbuild is fast (much faster than webpack)
- Tree-shaking reduces bundle size
- External modules reduce size (AWS SDK is 40MB+)
- Source maps enable debugging in CloudWatch


### Build-Time Constant Injection

**Pattern**: For Lambda@Edge or when you need smaller bundles.

```typescript
// In construct
bundling: {
  define: {
    'USER_POOL_ID': JSON.stringify(userPoolId),
    'CLIENT_ID': JSON.stringify(clientId),
    'REGION': JSON.stringify(region),
  },
}

// In Lambda code (declare for TypeScript)
declare const USER_POOL_ID: string;
declare const CLIENT_ID: string;
declare const REGION: string;

export const handler = async (event: any) => {
  console.log('User Pool:', USER_POOL_ID);  // Value baked in at build time
  console.log('Client:', CLIENT_ID);
  console.log('Region:', REGION);
};
```

**WHY**:
- Reduces bundle size (no environment variable overhead)
- Required for Lambda@Edge (size constraints)
- Values guaranteed to match deployed resources
- Faster cold starts (no environment parsing)


### Python Lambda Functions

**Pattern**: Use standard `lambda.Function` with `Code.fromAsset()` for Python functions. Avoid alpha constructs like `@aws-cdk/aws-lambda-python-alpha`.

**Simple Python Function (No External Dependencies)**:
```typescript
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as path from 'path';

// Directory structure:
// functions/my-function/
//   ├── index.py            # Handler code
//   └── requirements.txt    # Dependencies (boto3 already provided)

const myFunction = new lambda.Function(this, 'MyFunction', {
  runtime: lambda.Runtime.PYTHON_3_12,
  handler: 'index.handler',
  code: lambda.Code.fromAsset(path.join(__dirname, '../functions/my-function')),
  environment: {
    TABLE_NAME: table.tableName,
  },
  timeout: Duration.minutes(5),
  memorySize: 512,
});
```

**Python Function with External Dependencies (Bundling)**:
```typescript
const myFunction = new lambda.Function(this, 'MyFunction', {
  runtime: lambda.Runtime.PYTHON_3_12,
  handler: 'index.handler',
  code: lambda.Code.fromAsset(path.join(__dirname, '../functions/my-function'), {
    bundling: {
      image: lambda.Runtime.PYTHON_3_12.bundlingImage,
      command: [
        'bash', '-c',
        'pip install -r requirements.txt -t /asset-output && cp -au . /asset-output'
      ],
    },
  }),
  environment: {
    TABLE_NAME: table.tableName,
  },
});
```

**WHY**:
- No alpha dependencies (stable API, better support)
- `boto3` and `botocore` are already provided by Lambda runtime (no bundling needed for AWS SDK)
- Bundling only needed for external packages (requests, pandas, etc.)
- Simpler than alpha constructs
- Standard CDK pattern documented in official AWS docs
- Works with any Python version supported by Lambda

**When to Bundle**:
- ❌ **Don't bundle** if you only use `boto3`, `botocore`, `json`, `os`, `datetime` (provided by runtime)
- ✅ **Do bundle** if you use external packages like `requests`, `pandas`, `numpy`, `pillow`, etc.

**Example requirements.txt (no bundling needed)**:
```txt
boto3>=1.34.0
botocore>=1.34.0
```

**Example requirements.txt (bundling needed)**:
```txt
requests>=2.31.0
pandas>=2.0.0
pillow>=10.0.0
```

---

## 6. Deployment Patterns

### Comprehensive Deploy Script

**Pattern**: Create a deploy.sh script that handles the entire deployment workflow.

```bash
#!/bin/bash
# infrastructure/deploy.sh

set -e  # Exit on error

# ===================================
# Color Output
# ===================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_status() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
print_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ===================================
# Helper Functions
# ===================================
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# ===================================
# Prerequisites
# ===================================
check_prerequisites() {
    print_status "Checking prerequisites..."

    if ! command_exists node; then
        print_error "Node.js is not installed"
        exit 1
    fi

    if ! command_exists pnpm; then
        print_error "pnpm not installed. Install: npm install -g pnpm"
        exit 1
    fi

    if ! aws sts get-caller-identity >/dev/null 2>&1; then
        print_error "AWS credentials not configured"
        exit 1
    fi

    print_success "All prerequisites met"
}

# ===================================
# Environment Loading
# ===================================
load_env() {
    if [ -f .env ]; then
        print_status "Loading environment from .env"
        export $(grep -v '^#' .env | xargs)
    else
        print_error ".env file not found. Copy .env.example to .env"
        exit 1
    fi
}

# ===================================
# Validation
# ===================================
validate_env() {
    print_status "Validating environment variables..."

    local required_vars=(
        "ENVIRONMENT"
        "AWS_REGION"
        "AWS_ACCOUNT_ID"
    )

    for var in "${required_vars[@]}"; do
        if [ -z "${!var}" ]; then
            print_error "Required variable $var not set in .env"
            exit 1
        fi
    done

    print_success "Environment validated"
}

# ===================================
# CDK Bootstrap
# ===================================
bootstrap_cdk() {
    print_status "Checking CDK bootstrap..."

    if ! aws cloudformation describe-stacks \
        --stack-name CDKToolkit \
        --region "$AWS_REGION" >/dev/null 2>&1; then

        print_warning "Bootstrapping CDK..."
        npx cdk bootstrap "aws://${AWS_ACCOUNT_ID}/${AWS_REGION}"
    else
        print_success "CDK already bootstrapped"
    fi
}

# ===================================
# Deployment
# ===================================
deploy() {
    print_status "Installing dependencies..."
    pnpm install

    print_status "Compiling TypeScript..."
    pnpm build

    print_status "Synthesizing CloudFormation..."
    npx cdk synth

    print_status "Deploying stacks..."
    npx cdk deploy --all \
        --context environment="$ENVIRONMENT" \
        --require-approval never

    print_success "Deployment complete!"
}

# ===================================
# Main
# ===================================
main() {
    print_status "Starting deployment process..."

    load_env
    validate_env
    check_prerequisites
    bootstrap_cdk
    deploy
}

main "$@"
```

**WHY**:
- One command deploys everything
- Colored output improves UX
- Validates prerequisites before deployment
- Clear error messages with remediation steps
- Fails fast on errors
- Automatic CDK bootstrapping


### Phased Deployment Support

**Pattern**: For complex deployments with manual steps between phases.

```bash
case "${1:-all}" in
    all)
        deploy_all
        ;;
    stack1)
        deploy_stack1
        show_manual_steps
        ;;
    stack2)
        check_manual_steps_completed
        deploy_stack2
        ;;
    *)
        echo "Usage: $0 {all|stack1|stack2}"
        exit 1
        ;;
esac
```

**WHY**:
- Some deployments require manual configuration between phases
- Explicit phasing prevents incomplete deployments
- Clear separation of concerns
- Enables CI/CD to deploy specific components


### Output File Management

**Pattern**: Capture stack outputs for use in subsequent deployments.

```bash
npx cdk deploy "$stack_name" \
    --context environment="$ENVIRONMENT" \
    --outputs-file outputs.json

# Parse and display outputs
if [ -f outputs.json ]; then
    cat outputs.json | jq -r '.["'$stack_name'"]'
fi
```

**WHY**:
- Subsequent stacks can read outputs
- Manual configuration steps get required values
- Enables phased deployments
- Useful for CI/CD pipelines


---

## 7. Security Best Practices

### S3 Bucket Security

**Pattern**: Block all public access by default, use CloudFront with OAC.

```typescript
import { BlockPublicAccess, Bucket } from 'aws-cdk-lib/aws-s3';
import { OriginAccessControl, Distribution } from 'aws-cdk-lib/aws-cloudfront';
import { S3BucketOrigin } from 'aws-cdk-lib/aws-cloudfront-origins';

// Create private bucket
const bucket = new Bucket(this, 'WebsiteBucket', {
  bucketName: `${projectName}-${props.environment}-website`,

  // Security: Block all public access
  blockPublicAccess: BlockPublicAccess.BLOCK_ALL,

  // Encryption
  encryption: BucketEncryption.S3_MANAGED,

  // Versioning (production)
  versioned: props.environment === 'prod',

  // Environment-aware cleanup
  removalPolicy: props.environment === 'prod'
    ? RemovalPolicy.RETAIN
    : RemovalPolicy.DESTROY,
  autoDeleteObjects: props.environment !== 'prod',
});

// CloudFront with Origin Access Control (OAC)
const distribution = new Distribution(this, 'Distribution', {
  defaultBehavior: {
    origin: S3BucketOrigin.withOriginAccessControl(bucket),
    viewerProtocolPolicy: ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
  },
});
```

**WHY**:
- S3 buckets should NEVER be public
- Origin Access Control (OAC) is the modern replacement for OAI
- CloudFront provides the public interface
- Encryption at rest is a best practice
- Versioning protects production data


### Security Headers Policy

**Pattern**: Apply comprehensive security headers to all CloudFront responses.

```typescript
import {
  ResponseHeadersPolicy,
  HeadersFrameOption,
  HeadersReferrerPolicy,
} from 'aws-cdk-lib/aws-cloudfront';
import { Duration } from 'aws-cdk-lib';

const responseHeadersPolicy = new ResponseHeadersPolicy(this, 'SecurityHeaders', {
  securityHeadersBehavior: {
    // Content Security Policy
    contentSecurityPolicy: {
      contentSecurityPolicy: [
        "default-src 'self'",
        "connect-src 'self' https://api.example.com",
        "img-src 'self' data: https:",
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'",  // Minimize 'unsafe-*'
        "style-src 'self' 'unsafe-inline'",
        "font-src 'self' data:",
      ].join('; '),
      override: true,
    },

    // Prevent MIME type sniffing
    contentTypeOptions: {
      override: true,
    },

    // Prevent clickjacking
    frameOptions: {
      frameOption: HeadersFrameOption.DENY,
      override: true,
    },

    // Referrer policy
    referrerPolicy: {
      referrerPolicy: HeadersReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN,
      override: true,
    },

    // HTTPS enforcement
    strictTransportSecurity: {
      accessControlMaxAge: Duration.days(365),
      includeSubdomains: true,
      preload: true,
      override: true,
    },

    // XSS protection (legacy but still useful)
    xssProtection: {
      protection: true,
      modeBlock: true,
      override: true,
    },
  },
});

// Apply to distribution
const distribution = new Distribution(this, 'Distribution', {
  defaultBehavior: {
    origin: S3BucketOrigin.withOriginAccessControl(bucket),
    responseHeadersPolicy,
  },
});
```

**WHY**:
- CSP prevents XSS attacks
- HSTS enforces HTTPS
- Frame options prevent clickjacking
- Content type sniffing can lead to security issues
- These headers are security best practices for web applications


### HttpOnly Secure Cookies

**Pattern**: Authentication tokens should be in HttpOnly, Secure cookies.

```typescript
// In Lambda@Edge or API response
function createCookieHeader(name: string, value: string, maxAge: number): string {
  return [
    `${name}=${encodeURIComponent(value)}`,
    'Path=/',
    'HttpOnly',      // Prevents JavaScript access (XSS protection)
    'Secure',        // HTTPS only
    'SameSite=Lax',  // CSRF protection, allows OAuth redirects
    `Max-Age=${maxAge}`,
  ].join('; ');
}

// Usage
const headers = {
  'set-cookie': [{
    key: 'Set-Cookie',
    value: createCookieHeader('auth_token', token, 3600),
  }],
};
```

**WHY**:
- HttpOnly prevents XSS attacks (JavaScript can't read cookie)
- Secure ensures transmission only over HTTPS
- SameSite=Lax provides CSRF protection
- Max-Age is more reliable than Expires
- Path=/ makes cookie available to entire site


---

## 8. Frontend Integration

### Frontend Build as Part of CDK

**Pattern**: Build and deploy frontend as part of CDK deployment.

```typescript
import { BucketDeployment, Source } from 'aws-cdk-lib/aws-s3-deployment';
import { DockerImage } from 'aws-cdk-lib';
import { execSync } from 'child_process';
import * as fsExtra from 'fs-extra';

const bundle = Source.asset('../frontend', {
  bundling: {
    // Docker fallback (if local build fails)
    command: [
      'sh',
      '-c',
      'echo "Docker build not supported. Install dependencies locally."',
    ],
    image: DockerImage.fromRegistry('alpine'),

    // Local bundling (preferred)
    local: {
      tryBundle(outputDir: string): boolean {
        try {
          // Check if build tool exists
          execSync('pnpm --version', { stdio: 'ignore' });
        } catch {
          console.log('pnpm not installed. Skipping local bundling.');
          return false;
        }

        try {
          console.log('Building frontend with pnpm...');
          execSync('cd ../frontend && pnpm install && pnpm build', {
            stdio: 'inherit',
          });

          console.log('Copying frontend to CDK output...');
          fsExtra.copySync('../frontend/dist', outputDir, {
            overwrite: true,
          });

          return true;
        } catch (error) {
          console.error('Frontend build failed:', error);
          return false;
        }
      },
    },
  },
});

// Deploy to S3 with CloudFront invalidation
new BucketDeployment(this, 'DeployWebsite', {
  sources: [bundle],
  destinationBucket: props.siteBucket,
  distribution: props.distribution,
  distributionPaths: ['/*'],  // Invalidate all paths
});
```

**WHY**:
- Frontend and infrastructure always deployed together
- Configuration always matches deployed resources
- Local builds are faster (use local cache)
- Docker fallback for CI/CD environments
- Automatic CloudFront invalidation
- Single deployment command


### SPA Routing with CloudFront

**Pattern**: Configure error responses for client-side routing.

```typescript
const distribution = new Distribution(this, 'Distribution', {
  defaultBehavior: {
    origin: S3BucketOrigin.withOriginAccessControl(bucket),
  },

  // SPA error handling
  errorResponses: [
    {
      httpStatus: 403,           // S3 returns 403 when object not found
      responseHttpStatus: 200,   // Return 200 to browser
      responsePagePath: '/index.html',  // Serve index.html
      ttl: Duration.minutes(0),  // Don't cache error responses
    },
    // Note: Don't add 404 error response if you have API routes
    // It will intercept API 404s before Lambda@Edge can handle them
  ],
});
```

**WHY**:
- SPAs use client-side routing (React Router, Vue Router, etc.)
- All routes need to serve index.html
- React Router handles routing client-side
- S3 returns 403 for non-existent objects (not 404)
- Zero TTL prevents caching of error responses


---

## 9. TypeScript Configuration

### Recommended tsconfig.json

```json
{
  "compilerOptions": {
    // Modern JavaScript
    "target": "ES2022",
    "module": "nodenext",
    "moduleResolution": "nodenext",
    "lib": ["es2022"],

    // Output
    "outDir": "dist",
    "declaration": true,
    "inlineSourceMap": true,
    "inlineSources": true,

    // Strict Type Checking
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "noImplicitThis": true,
    "alwaysStrict": true,

    // Additional Checks (relaxed for CDK)
    "noUnusedLocals": false,       // CDK constructs often have unused IDs
    "noUnusedParameters": false,
    "noImplicitReturns": true,
    "noFallthroughCasesInSwitch": true,
    "strictPropertyInitialization": false,  // CDK doesn't always init in constructor

    // Module Resolution
    "esModuleInterop": true,
    "resolveJsonModule": true,
    "allowSyntheticDefaultImports": true,

    // Path Aliases
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"],
      "@constructs/*": ["src/constructs/*"],
      "@stacks/*": ["src/stacks/*"]
    },

    // Decorators (if using)
    "experimentalDecorators": true,
    "emitDecoratorMetadata": true,

    // Type Roots
    "typeRoots": ["node_modules/@types"]
  },
  "include": ["src/**/*.ts"],
  "exclude": ["node_modules", "cdk.out", "dist", "test"]
}
```

**WHY**:
- **ES2022**: Modern features (top-level await, etc.)
- **nodenext**: Proper ESM/CommonJS interop
- **strict: true**: Maximum type safety
- **outDir: "dist"**: Separate source from compiled
- **inlineSourceMap**: Debugging without separate files
- **noUnusedLocals: false**: CDK often has unused variables (construct IDs)
- **strictPropertyInitialization: false**: CDK constructs don't follow traditional init patterns
- **Path aliases**: Cleaner imports (`@/constructs/foo` vs `../constructs/foo`)


### Using Path Aliases

```typescript
// Instead of:
import { WebsiteConstruct } from '../../../constructs/website-construct';
import { ApiConstruct } from '../../../constructs/api-construct';

// Use:
import { WebsiteConstruct } from '@constructs/website-construct';
import { ApiConstruct } from '@constructs/api-construct';

// Or:
import { WebsiteConstruct } from '@/constructs/website-construct';
```

**WHY**:
- Cleaner, more readable imports
- Refactoring-friendly (move files without fixing imports)
- No `../../../` chains

---

## 10. Quick Start Checklist

Use this checklist when starting a new CDK project following this template.

### Initial Setup

- [ ] Create project structure
  ```bash
  mkdir -p infrastructure/src/{stacks,constructs,functions}
  mkdir -p docs
  ```

- [ ] Initialize CDK project
  ```bash
  cd infrastructure
  pnpm init
  pnpm add -D aws-cdk-lib constructs typescript ts-node @types/node
  pnpm add -D dotenv
  npx cdk init --language=typescript
  ```

- [ ] Configure TypeScript (use template from Section 9)
  - Copy tsconfig.json with path aliases
  - Set `outDir: "dist"`

- [ ] Configure CDK
  - Update cdk.json with feature flags
  - Set app entry: `"app": "npx ts-node --prefer-ts-exts src/main.ts"`

- [ ] Create environment configuration
  - Create `.env.example` with all required variables
  - Add `.env` to .gitignore
  - Copy `.env.example` to `.env` and fill in values

- [ ] Update .gitignore
  ```
  # Build artifacts
  dist/
  cdk.out/

  # Environment
  .env

  # Outputs
  *-outputs.json

  # Keep examples
  !.env.example
  ```

### Project Files

- [ ] Create main.ts entry point
  - Load dotenv
  - Get configuration from env
  - Instantiate stacks

- [ ] Create first stack (thin orchestrator)
  - Extends Stack
  - Takes environment in props
  - Delegates to constructs
  - Adds CloudFormation outputs

- [ ] Create first construct (business logic)
  - Encapsulates complete pattern
  - Validates props in constructor
  - Environment-aware policies
  - Exposes resources via public properties

- [ ] Create deploy.sh script
  - Colored output helpers
  - Prerequisite checking
  - Environment loading and validation
  - CDK bootstrapping
  - Deployment with error handling

### Development Workflow

- [ ] Make deploy.sh executable
  ```bash
  chmod +x infrastructure/deploy.sh
  ```

- [ ] Set up AWS credentials
  ```bash
  aws configure
  # or export AWS_PROFILE=your-profile
  ```

- [ ] Configure environment
  ```bash
  cp infrastructure/.env.example infrastructure/.env
  # Edit .env with your values
  ```

- [ ] Synth to validate
  ```bash
  cd infrastructure
  pnpm build
  npx cdk synth
  ```

- [ ] Deploy
  ```bash
  ./deploy.sh
  ```

### Best Practices Checklist

- [ ] All secrets in .env (never in code)
- [ ] Production resources use RETAIN policy
- [ ] S3 buckets block public access
- [ ] Security headers on CloudFront
- [ ] Environment-aware log retention
- [ ] Path aliases configured
- [ ] Constructs are reusable
- [ ] Stacks are thin orchestrators
- [ ] Cross-stack refs use SSM Parameter Store
- [ ] Deploy script validates prerequisites
- [ ] Error messages include remediation steps

---

## Related Documentation

- **Cognito Authentication Pattern**: See [CDK_COGNITO_PATTERN.md](./CDK_COGNITO_PATTERN.md) for detailed Cognito + OIDC implementation
- **Reference Project**: `/Users/schuettc/GitHub/3pmod/claude-code-resources`

---

## Questions or Improvements?

This is a living document. If you find better patterns or have questions, update this document or ask the team.
