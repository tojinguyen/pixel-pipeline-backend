from botocore.exceptions import NoCredentialsError

from app.core.config import get_settings
from app.core.exceptions import StorageError
from app.infrastructure.storage.s3_client import get_s3_client


def upload_file(file_bytes: bytes, filename: str, content_type: str = "image/png") -> str:
    settings = get_settings()
    client = get_s3_client()

    try:
        client.put_object(
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
