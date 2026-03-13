import asyncio

from botocore.exceptions import ClientError
from botocore.exceptions import NoCredentialsError

from app.core.config import get_settings
from app.core.exceptions import StorageError


async def upload_file_async(
    file_bytes: bytes,
    object_key: str,
    content_type: str,
    client,
) -> str:
    """
    Offload the boto3 S3 upload (blocking I/O) to a thread pool to avoid
    blocking FastAPI's async event loop.
    """
    settings = get_settings()
    try:
        await asyncio.to_thread(
            client.put_object,
            Bucket=settings.s3_bucket_name,
            Key=object_key,
            Body=file_bytes,
            ContentType=content_type,
        )
        return object_key
    except NoCredentialsError as exc:
        raise StorageError("Credentials not available") from exc
    except Exception as exc:
        raise StorageError(f"Error uploading to S3: {exc}") from exc


async def download_file_async(object_key: str, client) -> bytes:
    settings = get_settings()

    try:
        return await asyncio.to_thread(_download_file, client, settings.s3_bucket_name, object_key)
    except NoCredentialsError as exc:
        raise StorageError("Credentials not available") from exc
    except ClientError as exc:
        raise StorageError(f"Error downloading from S3: {exc}") from exc
    except Exception as exc:
        raise StorageError(f"Error downloading from S3: {exc}") from exc


def _download_file(client, bucket_name: str, object_key: str) -> bytes:
    response = client.get_object(Bucket=bucket_name, Key=object_key)
    body = response["Body"]
    try:
        return body.read()
    finally:
        body.close()


def get_file_url(object_key: str) -> str:
    settings = get_settings()
    if settings.s3_public_endpoint_url:
        return f"{settings.s3_public_endpoint_url}/{settings.s3_bucket_name}/{object_key}"
    return f"https://{settings.s3_bucket_name}.s3.{settings.aws_region}.amazonaws.com/{object_key}"
