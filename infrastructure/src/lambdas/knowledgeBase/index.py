"""
Custom Resource Lambda handler for Bedrock Knowledge Base with S3 Vectors.

This Lambda manages the lifecycle of:
- S3 Vectors bucket and index
- Bedrock Knowledge Base
- Data source configuration
- Initial ingestion job

S3 Vectors is ~100x cheaper than OpenSearch Serverless for vector storage.
"""

import hashlib
import json
import logging
import time
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize clients
bedrock_agent = boto3.client("bedrock-agent")
s3vectors = boto3.client("s3vectors")
s3 = boto3.client("s3")


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    CloudFormation Custom Resource handler.

    Properties:
        VectorBucketName: Name for the S3 Vectors bucket
        KnowledgeBaseName: Name for the Bedrock Knowledge Base
        DocumentBucketArn: ARN of S3 bucket containing source documents
        DocumentBucketName: Name of S3 bucket containing source documents
        BedrockRoleArn: IAM role ARN for Bedrock to access resources
        EmbeddingModelArn: ARN of the embedding model (e.g., Titan Embeddings)
        ConfigHash: Hash of configuration for change detection
    """
    logger.info("Event received: %s", json.dumps(event, default=str))

    request_type = event["RequestType"]
    properties = event["ResourceProperties"]

    try:
        if request_type == "Create":
            return on_create(properties)
        elif request_type == "Update":
            old_properties = event.get("OldResourceProperties", {})
            return on_update(properties, old_properties)
        elif request_type == "Delete":
            physical_id = event.get("PhysicalResourceId")
            return on_delete(properties, physical_id)
        else:
            raise ValueError(f"Unknown request type: {request_type}")
    except Exception as e:
        logger.exception("Error handling request")
        raise


def on_create(properties: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create S3 Vectors bucket, index, Knowledge Base, and data source.
    """
    vector_bucket_name = properties["VectorBucketName"]
    kb_name = properties["KnowledgeBaseName"]
    doc_bucket_arn = properties["DocumentBucketArn"]
    doc_bucket_name = properties["DocumentBucketName"]
    bedrock_role_arn = properties["BedrockRoleArn"]
    embedding_model_arn = properties["EmbeddingModelArn"]

    logger.info("Creating Knowledge Base resources...")

    # Step 1: Create S3 Vectors bucket
    logger.info("Creating S3 Vectors bucket: %s", vector_bucket_name)
    try:
        s3vectors.create_vector_bucket(vectorBucketName=vector_bucket_name)
        logger.info("S3 Vectors bucket created successfully")
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in ["VectorBucketAlreadyExists", "ConflictException"]:
            logger.info("S3 Vectors bucket already exists, continuing...")
        else:
            raise

    # Wait for bucket to be ready
    _wait_for_vector_bucket(vector_bucket_name)

    # Step 2: Create index with Titan Embeddings config
    index_name = "default-index"
    logger.info("Creating S3 Vectors index: %s", index_name)
    try:
        s3vectors.create_index(
            vectorBucketName=vector_bucket_name,
            indexName=index_name,
            dimension=1024,  # Titan Embeddings v2 uses 1024 dimensions
            distanceMetric="cosine",
            dataType="float32",
            metadataConfiguration={
                "nonFilterableMetadataKeys": [
                    "AMAZON_BEDROCK_TEXT",
                    "AMAZON_BEDROCK_METADATA",
                ]
            },
        )
        logger.info("S3 Vectors index created successfully")
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in ["IndexAlreadyExists", "ConflictException"]:
            logger.info("S3 Vectors index already exists, continuing...")
        else:
            raise

    # Get index ARN - wait for index to be ready
    index_arn = _wait_for_index_ready(vector_bucket_name, index_name)
    logger.info("Index ARN: %s", index_arn)

    # Step 3: Create Knowledge Base
    logger.info("Creating Bedrock Knowledge Base: %s", kb_name)
    try:
        kb_response = bedrock_agent.create_knowledge_base(
            name=kb_name,
            description="Voice Agent Knowledge Base for RAG",
            roleArn=bedrock_role_arn,
            knowledgeBaseConfiguration={
                "type": "VECTOR",
                "vectorKnowledgeBaseConfiguration": {
                    "embeddingModelArn": embedding_model_arn,
                },
            },
            storageConfiguration={
                "type": "S3_VECTORS",
                "s3VectorsConfiguration": {
                    "indexArn": index_arn,
                },
            },
        )
        knowledge_base_id = kb_response["knowledgeBase"]["knowledgeBaseId"]
        knowledge_base_arn = kb_response["knowledgeBase"]["knowledgeBaseArn"]
        logger.info("Knowledge Base created: %s", knowledge_base_id)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "ConflictException":
            # KB with this name already exists, find and use it
            logger.info(
                "Knowledge Base with name '%s' already exists, looking it up...",
                kb_name,
            )
            list_response = bedrock_agent.list_knowledge_bases()
            for kb in list_response.get("knowledgeBaseSummaries", []):
                if kb.get("name") == kb_name:
                    knowledge_base_id = kb.get("knowledgeBaseId")
                    # Get full details
                    kb_details = bedrock_agent.get_knowledge_base(
                        knowledgeBaseId=knowledge_base_id
                    )
                    knowledge_base_arn = kb_details["knowledgeBase"]["knowledgeBaseArn"]
                    logger.info("Found existing Knowledge Base: %s", knowledge_base_id)
                    break
            else:
                raise ValueError(
                    f"Knowledge Base '{kb_name}' reported as existing but could not be found"
                )
        else:
            raise

    # Wait for KB to be active
    _wait_for_knowledge_base(knowledge_base_id, "ACTIVE")

    # Step 4: Create Data Source
    logger.info("Creating data source for bucket: %s", doc_bucket_name)
    data_source_name = f"{kb_name}-documents"
    try:
        ds_response = bedrock_agent.create_data_source(
            knowledgeBaseId=knowledge_base_id,
            name=data_source_name,
            description="Document source for voice agent knowledge base",
            dataSourceConfiguration={
                "type": "S3",
                "s3Configuration": {
                    "bucketArn": doc_bucket_arn,
                },
            },
        )
        data_source_id = ds_response["dataSource"]["dataSourceId"]
        logger.info("Data source created: %s", data_source_id)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "ConflictException":
            # Data source already exists, find and use it
            logger.info(
                "Data source '%s' already exists, looking it up...", data_source_name
            )
            list_response = bedrock_agent.list_data_sources(
                knowledgeBaseId=knowledge_base_id
            )
            for ds in list_response.get("dataSourceSummaries", []):
                if ds.get("name") == data_source_name:
                    data_source_id = ds.get("dataSourceId")
                    logger.info("Found existing data source: %s", data_source_id)
                    break
            else:
                raise ValueError(
                    f"Data source '{data_source_name}' reported as existing but could not be found"
                )
        else:
            raise

    # Step 5: Start initial ingestion job
    logger.info("Starting initial ingestion job...")
    try:
        bedrock_agent.start_ingestion_job(
            knowledgeBaseId=knowledge_base_id,
            dataSourceId=data_source_id,
        )
        logger.info("Ingestion job started")
    except ClientError as e:
        # Ingestion may fail if bucket is empty - that's ok
        logger.warning("Could not start ingestion: %s", e)

    physical_id = f"{knowledge_base_id}:{data_source_id}:{vector_bucket_name}"

    return {
        "PhysicalResourceId": physical_id,
        "Data": {
            "KnowledgeBaseId": knowledge_base_id,
            "KnowledgeBaseArn": knowledge_base_arn,
            "DataSourceId": data_source_id,
            "VectorBucketName": vector_bucket_name,
            "IndexArn": index_arn,
        },
    }


def on_update(
    properties: Dict[str, Any],
    old_properties: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Handle updates. Re-creates if significant config changed.
    """
    # Compare config hashes
    new_hash = properties.get("ConfigHash", "")
    old_hash = old_properties.get("ConfigHash", "")

    if new_hash != old_hash:
        logger.info("Config changed, re-creating resources...")
        # Delete old and create new
        # Note: Full recreation for simplicity
        # In production, you might want more granular updates
        return on_create(properties)

    # No significant changes - return existing
    logger.info("No config changes detected")

    # Re-trigger ingestion in case documents changed
    knowledge_base_id = properties.get("_KnowledgeBaseId")
    data_source_id = properties.get("_DataSourceId")

    if knowledge_base_id and data_source_id:
        try:
            bedrock_agent.start_ingestion_job(
                knowledgeBaseId=knowledge_base_id,
                dataSourceId=data_source_id,
            )
            logger.info("Ingestion job started on update")
        except ClientError as e:
            logger.warning("Could not start ingestion: %s", e)

    return {
        "PhysicalResourceId": properties.get("_PhysicalResourceId", "unchanged"),
        "Data": {},
    }


def on_delete(
    properties: Dict[str, Any],
    physical_id: Optional[str],
) -> Dict[str, Any]:
    """
    Delete Knowledge Base, data source, S3 Vectors index, and bucket.
    """
    if not physical_id or physical_id == "unchanged":
        logger.info("No physical resource ID, skipping delete")
        return {"PhysicalResourceId": physical_id or "none"}

    # Parse physical ID
    parts = physical_id.split(":")
    if len(parts) != 3:
        logger.warning("Invalid physical ID format: %s", physical_id)
        return {"PhysicalResourceId": physical_id}

    knowledge_base_id, data_source_id, vector_bucket_name = parts

    # Step 1: Delete data source
    logger.info("Deleting data source: %s", data_source_id)
    try:
        bedrock_agent.delete_data_source(
            knowledgeBaseId=knowledge_base_id,
            dataSourceId=data_source_id,
        )
        logger.info("Data source deleted")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.info("Data source already deleted")
        else:
            logger.warning("Error deleting data source: %s", e)

    # Step 2: Delete Knowledge Base
    logger.info("Deleting Knowledge Base: %s", knowledge_base_id)
    try:
        bedrock_agent.delete_knowledge_base(knowledgeBaseId=knowledge_base_id)
        _wait_for_knowledge_base_deleted(knowledge_base_id)
        logger.info("Knowledge Base deleted")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.info("Knowledge Base already deleted")
        else:
            logger.warning("Error deleting Knowledge Base: %s", e)

    # Step 3: Delete S3 Vectors index
    index_name = "default-index"
    logger.info("Deleting S3 Vectors index: %s", index_name)
    try:
        s3vectors.delete_index(
            vectorBucketName=vector_bucket_name,
            indexName=index_name,
        )
        logger.info("S3 Vectors index deleted")
    except ClientError as e:
        if e.response["Error"]["Code"] == "IndexNotFound":
            logger.info("S3 Vectors index already deleted")
        else:
            logger.warning("Error deleting index: %s", e)

    # Step 4: Delete S3 Vectors bucket
    logger.info("Deleting S3 Vectors bucket: %s", vector_bucket_name)
    try:
        s3vectors.delete_vector_bucket(vectorBucketName=vector_bucket_name)
        logger.info("S3 Vectors bucket deleted")
    except ClientError as e:
        if e.response["Error"]["Code"] == "VectorBucketNotFound":
            logger.info("S3 Vectors bucket already deleted")
        else:
            logger.warning("Error deleting vector bucket: %s", e)

    return {"PhysicalResourceId": physical_id}


def _wait_for_vector_bucket(bucket_name: str, max_attempts: int = 30) -> None:
    """Wait for S3 Vectors bucket to be ready.

    The S3 Vectors API returns bucket info under 'vectorBucket' key.
    When the bucket is returned successfully, it's ready to use.
    """
    for i in range(max_attempts):
        try:
            response = s3vectors.get_vector_bucket(vectorBucketName=bucket_name)
            # If we get a response with vectorBucket, the bucket is ready
            if "vectorBucket" in response:
                bucket_info = response["vectorBucket"]
                logger.info(
                    "Vector bucket ready: %s (ARN: %s)",
                    bucket_info.get("vectorBucketName"),
                    bucket_info.get("vectorBucketArn"),
                )
                return
            logger.info("Vector bucket response incomplete, waiting...")
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ["VectorBucketNotFound", "ResourceNotFoundException"]:
                logger.info(
                    "Vector bucket not found yet, waiting... (attempt %d/%d)",
                    i + 1,
                    max_attempts,
                )
            else:
                raise
        time.sleep(2)
    raise TimeoutError(f"Vector bucket {bucket_name} did not become active")


def _wait_for_index_ready(
    bucket_name: str, index_name: str, max_attempts: int = 30
) -> str:
    """Wait for S3 Vectors index to be ready and return its ARN.

    The S3 Vectors API returns index info under 'index' key.
    """
    for i in range(max_attempts):
        try:
            response = s3vectors.get_index(
                vectorBucketName=bucket_name,
                indexName=index_name,
            )
            # Response structure: {"index": {"indexArn": "...", "indexName": "...", ...}}
            if "index" in response:
                index_info = response["index"]
                index_arn = index_info.get("indexArn")
                if index_arn:
                    logger.info(
                        "Index ready: %s (ARN: %s)",
                        index_info.get("indexName"),
                        index_arn,
                    )
                    return index_arn
            logger.info(
                "Index response incomplete, waiting... (attempt %d/%d)",
                i + 1,
                max_attempts,
            )
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ["IndexNotFound", "ResourceNotFoundException"]:
                logger.info(
                    "Index not found yet, waiting... (attempt %d/%d)",
                    i + 1,
                    max_attempts,
                )
            else:
                raise
        time.sleep(2)
    raise TimeoutError(
        f"Index {index_name} in bucket {bucket_name} did not become ready"
    )


def _wait_for_knowledge_base(
    kb_id: str, target_status: str, max_attempts: int = 60
) -> None:
    """Wait for Knowledge Base to reach target status."""
    for i in range(max_attempts):
        response = bedrock_agent.get_knowledge_base(knowledgeBaseId=kb_id)
        status = response["knowledgeBase"]["status"]
        if status == target_status:
            return
        if status in ["FAILED", "DELETE_UNSUCCESSFUL"]:
            raise ValueError(f"Knowledge Base entered failed state: {status}")
        logger.info(
            "Knowledge Base status: %s, waiting for %s...", status, target_status
        )
        time.sleep(5)
    raise TimeoutError(f"Knowledge Base {kb_id} did not reach {target_status}")


def _wait_for_knowledge_base_deleted(kb_id: str, max_attempts: int = 60) -> None:
    """Wait for Knowledge Base to be deleted."""
    for i in range(max_attempts):
        try:
            response = bedrock_agent.get_knowledge_base(knowledgeBaseId=kb_id)
            status = response["knowledgeBase"]["status"]
            logger.info("Knowledge Base status: %s, waiting for deletion...", status)
            time.sleep(5)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                return
            raise
    raise TimeoutError(f"Knowledge Base {kb_id} was not deleted")
