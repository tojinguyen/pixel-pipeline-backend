import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_region: str
    s3_bucket_name: str
    s3_endpoint_url: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "minioadmin"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin"),
        aws_region=os.getenv("AWS_REGION", "us-east-1"),
        s3_bucket_name=os.getenv("S3_BUCKET_NAME", "pixel-pipeline"),
        s3_endpoint_url=os.getenv("S3_ENDPOINT_URL", "http://localhost:9000"),
    )
