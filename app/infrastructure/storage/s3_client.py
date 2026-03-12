import boto3
from botocore.client import BaseClient

from app.core.config import get_settings


def init_s3_client() -> BaseClient:
    """
    Initialize and return a boto3 S3 client.
    The caller is responsible for storing the returned client (e.g., in app.state).
    """
    settings = get_settings()
    client = boto3.client(
        "s3",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
        endpoint_url=settings.s3_endpoint_url or None,
    )
    return client
