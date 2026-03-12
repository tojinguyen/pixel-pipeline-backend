from fastapi import Request
from botocore.client import BaseClient


def get_s3_client(request: Request) -> BaseClient:
    """Retrieve the S3 client stored in app.state during lifespan startup."""
    return request.app.state.s3_client


def get_rembg_session(request: Request):
    """Retrieve the rembg session stored in app.state during lifespan startup."""
    return request.app.state.rembg_session
