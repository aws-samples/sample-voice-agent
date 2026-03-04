# CDK Deprecation Cleanup V2 - Implementation Plan

## Executive Summary

This plan addresses two critical CDK deprecation warnings that need resolution before the next major CDK release:
1. **Lambda logRetention → logGroup migration** in Custom Resource Provider
2. **url.parse() → WHATWG URL API migration** (dependency-level issue)

## 1. Expanded Requirements

### 1.1 Lambda logRetention Migration

**Current Issue:**
- `aws-cdk-lib.aws_lambda.FunctionOptions#logRetention` is deprecated in CDK v2.175.1+
- Found in: `/infrastructure/src/constructs/knowledge-base-construct.ts:258`
- Used by: Custom Resource Provider for Knowledge Base management

**Technical Requirements:**
- Replace `logRetention` property with explicit `logGroup` creation
- Maintain current retention policy (ONE_WEEK)
- Ensure log group naming follows AWS Lambda conventions
- Preserve existing functionality and permissions

### 1.2 url.parse() Migration

**Current Issue:**
- Node.js `url.parse()` is deprecated with security implications
- Not found in direct codebase usage
- Likely exists in transitive dependencies
- Requires dependency audit and potential package updates

**Technical Requirements:**
- Identify packages using deprecated `url.parse()`
- Update or replace affected dependencies
- Ensure WHATWG URL API compatibility
- Maintain backward compatibility where possible

## 2. Implementation Steps

### 2.1 Lambda logRetention Fix

#### Step 1: Locate and Analyze Current Usage
```bash
# Already identified in knowledge-base-construct.ts line 258
grep -n "logRetention" infrastructure/src/constructs/knowledge-base-construct.ts
```

#### Step 2: Create Explicit Log Group
**File:** `/infrastructure/src/constructs/knowledge-base-construct.ts`

**Current Code (around line 256-259):**
```typescript
const provider = new cr.Provider(this, 'KnowledgeBaseProvider', {
  onEventHandler: kbManagementLambda,
  logRetention: logs.RetentionDays.ONE_WEEK,
});
```

**Updated Code:**
```typescript
// Create explicit log group for Custom Resource Provider
const providerLogGroup = new logs.LogGroup(this, 'KnowledgeBaseProviderLogGroup', {
  logGroupName: `/aws/lambda/${resourcePrefix}-kb-provider`,
  retention: logs.RetentionDays.ONE_WEEK,
  removalPolicy: cdk.RemovalPolicy.DESTROY,
});

const provider = new cr.Provider(this, 'KnowledgeBaseProvider', {
  onEventHandler: kbManagementLambda,
  logGroup: providerLogGroup,
});
```

#### Step 3: Update Imports
Ensure `logs` is imported:
```typescript
import * as logs from 'aws-cdk-lib/aws-logs';
```

#### Step 4: Test the Changes
```bash
cd infrastructure
npm run build
npm run synth
```

### 2.2 url.parse() Dependency Audit

#### Step 1: Identify Affected Dependencies
```bash
# Check for url.parse usage in node_modules
cd infrastructure
npm audit --audit-level=moderate
npm ls --depth=0
```

#### Step 2: Deep Dependency Analysis
```bash
# Search for url.parse in all dependencies
find node_modules -name "*.js" -exec grep -l "url\.parse" {} \; 2>/dev/null | head -10

# Check package-lock.json for URL-related packages
grep -i "url" package-lock.json | grep -v "node_modules"
```

#### Step 3: Update Strategy
Based on findings:
- **If in direct dependencies:** Update to latest versions
- **If in transitive dependencies:** Update parent packages or find alternatives
- **If in CDK itself:** Wait for CDK team fix or use workarounds

#### Step 4: Package Updates
```bash
# Update all packages to latest compatible versions
npm update
npm audit fix

# If specific packages need replacement, update package.json
```

## 3. Acceptance Criteria

### 3.1 Lambda logRetention Migration Success Criteria

✅ **No Deprecation Warnings**
```bash
cd infrastructure
npm run synth 2>&1 | grep -i "deprecated\|logRetention"
# Should return no results
```

✅ **Successful Deployment**
```bash
npm run deploy
# Should complete without errors
```

✅ **Log Group Creation Verification**
```bash
# Verify log group exists with correct name and retention
aws logs describe-log-groups --log-group-name-prefix "/aws/lambda/voice-agent-poc-kb-provider"
```

✅ **Functional Testing**
- Knowledge Base creation/update operations work correctly
- Custom Resource Provider logs appear in the new log group
- No permission errors in CloudWatch logs

### 3.2 url.parse() Migration Success Criteria

✅ **No Security Warnings**
```bash
npm audit --audit-level=moderate
# Should show no url.parse related vulnerabilities
```

✅ **Clean Dependency Tree**
```bash
# No deprecated url.parse usage in dependencies
find node_modules -name "*.js" -exec grep -l "url\.parse" {} \; 2>/dev/null | wc -l
# Should return 0 or significantly reduced count
```

✅ **Application Functionality**
- All CDK constructs deploy successfully
- No runtime errors related to URL parsing
- All existing functionality preserved

## 4. Risks & Considerations

### 4.1 Lambda logRetention Migration Risks

**🔴 High Risk: Log Group Naming Conflicts**
- **Issue:** Custom Resource Provider log group names must not conflict
- **Mitigation:** Use unique, predictable naming pattern
- **Rollback:** Keep old provider temporarily during transition

**🟡 Medium Risk: CloudFormation Update Behavior**
- **Issue:** Changing log configuration might trigger resource replacement
- **Mitigation:** Test in non-production environment first
- **Rollback:** Revert to logRetention temporarily if issues arise

**🟢 Low Risk: Permission Changes**
- **Issue:** Explicit log group might need different IAM permissions
- **Mitigation:** CDK automatically handles log group permissions
- **Rollback:** Standard CDK rollback procedures

### 4.2 url.parse() Migration Risks

**🔴 High Risk: Breaking Changes in Dependencies**
- **Issue:** Updated packages might introduce breaking changes
- **Mitigation:** 
  - Update packages incrementally
  - Test thoroughly after each update
  - Pin versions in package-lock.json
- **Rollback:** Revert to previous package-lock.json

**🟡 Medium Risk: Transitive Dependency Issues**
- **Issue:** url.parse() might be deep in dependency tree
- **Mitigation:**
  - Use `npm ls` to identify dependency paths
  - Contact package maintainers if needed
  - Consider alternative packages
- **Rollback:** Use npm shrinkwrap to lock versions

**🟢 Low Risk: CDK Framework Dependencies**
- **Issue:** CDK itself might use url.parse()
- **Mitigation:** 
  - Monitor CDK release notes
  - Update to latest CDK version
  - Report issues to AWS CDK team
- **Rollback:** Pin CDK version until fix available

## 5. Testing Strategy

### 5.1 Pre-Implementation Testing
```bash
# Baseline: Capture current warnings
cd infrastructure
npm run synth 2>&1 | grep -i "deprecated" > /tmp/before-warnings.txt
```

### 5.2 Post-Implementation Testing
```bash
# Verify warnings are resolved
npm run synth 2>&1 | grep -i "deprecated" > /tmp/after-warnings.txt
diff /tmp/before-warnings.txt /tmp/after-warnings.txt

# Full deployment test
npm run deploy --all

# Functional verification
# Test Knowledge Base operations through the application
```

### 5.3 Rollback Procedures
```bash
# If issues arise, rollback steps:
git checkout HEAD~1 -- infrastructure/src/constructs/knowledge-base-construct.ts
npm install  # Restore previous package-lock.json if needed
npm run deploy
```

## 6. Success Metrics

- **Zero deprecation warnings** during CDK synth/deploy
- **No functional regressions** in Knowledge Base operations
- **Clean security audit** with no url.parse vulnerabilities
- **Successful deployment** in all environments
- **Documentation updated** to reflect changes

## 7. Timeline

- **Phase 1** (Day 1): Lambda logRetention migration and testing
- **Phase 2** (Day 2): url.parse() dependency audit and updates
- **Phase 3** (Day 3): Integration testing and deployment verification
- **Total Effort**: 2-3 days

## 8. Dependencies

- CDK version: 2.175.1+ (current: 2.175.1)
- Node.js version: 18+ (current requirement)
- AWS CLI access for verification
- Non-production environment for testing

---

**Next Steps:**
1. Begin with Lambda logRetention migration (lower risk)
2. Test thoroughly in development environment
3. Proceed with dependency audit for url.parse()
4. Deploy to production after all tests pass