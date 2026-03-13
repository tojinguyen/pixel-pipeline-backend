import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

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
    _ensure_bucket_exists(client)
    return client


def _ensure_bucket_exists(client: BaseClient) -> None:
    settings = get_settings()

    try:
        client.head_bucket(Bucket=settings.s3_bucket_name)
        return
    except ClientError:
        create_bucket_kwargs = {"Bucket": settings.s3_bucket_name}
        if not settings.s3_endpoint_url and settings.aws_region != "us-east-1":
            create_bucket_kwargs["CreateBucketConfiguration"] = {
                "LocationConstraint": settings.aws_region,
            }
        client.create_bucket(**create_bucket_kwargs)
