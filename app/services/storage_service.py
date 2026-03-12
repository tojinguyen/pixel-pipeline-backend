import asyncio

from botocore.exceptions import NoCredentialsError

from app.core.config import get_settings
from app.core.exceptions import StorageError


async def upload_file_async(
    file_bytes: bytes,
    filename: str,
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
            Key=filename,
            Body=file_bytes,
            ContentType=content_type,
        )
        return filename
    except NoCredentialsError as exc:
        raise StorageError("Credentials not available") from exc
    except Exception as exc:
        raise StorageError(f"Error uploading to S3: {exc}") from exc


def get_file_url(filename: str) -> str:
    settings = get_settings()
    if settings.s3_endpoint_url:
        return f"{settings.s3_endpoint_url}/{settings.s3_bucket_name}/{filename}"
    return f"https://{settings.s3_bucket_name}.s3.{settings.aws_region}.amazonaws.com/{filename}"
