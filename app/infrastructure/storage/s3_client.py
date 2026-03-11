from __future__ import annotations

import boto3
from botocore.client import BaseClient

from app.core.config import get_settings
from app.core.exceptions import StorageError
from app.core.logging import get_logger


logger = get_logger(__name__)
_s3_client: BaseClient | None = None


def init_s3_client() -> None:
    global _s3_client
    settings = get_settings()
    _s3_client = boto3.client(
        "s3",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
        endpoint_url=settings.s3_endpoint_url or None,
    )
    _ensure_bucket_exists()


def get_s3_client() -> BaseClient:
    if _s3_client is None:
        raise StorageError("S3 client is not initialized")
    return _s3_client


def _ensure_bucket_exists() -> None:
    settings = get_settings()
    client = get_s3_client()

    try:
        client.head_bucket(Bucket=settings.s3_bucket_name)
        return
    except Exception:
        pass

    try:
        if settings.aws_region == "us-east-1":
            client.create_bucket(Bucket=settings.s3_bucket_name)
        else:
            client.create_bucket(
                Bucket=settings.s3_bucket_name,
                CreateBucketConfiguration={"LocationConstraint": settings.aws_region},
            )
        logger.info("Created bucket '%s'", settings.s3_bucket_name)
    except Exception as exc:
        logger.warning("Could not create bucket '%s': %s", settings.s3_bucket_name, exc)
