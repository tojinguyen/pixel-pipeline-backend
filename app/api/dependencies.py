from collections.abc import AsyncIterator

from fastapi import HTTPException, Request
from botocore.client import BaseClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.session import get_db_session
from app.infrastructure.imaging.rembg_client import init_rembg_session


def get_s3_client(request: Request) -> BaseClient:
    """Retrieve the S3 client stored in app.state during lifespan startup."""
    return request.app.state.s3_client


def get_rembg_session(request: Request):
    """Lazily initialize rembg session on first use.

    This keeps API docs and non-rembg endpoints available even when the optional
    onnxruntime backend is not installed yet.
    """
    session = request.app.state.rembg_session
    if session is not None:
        return session

    try:
        session = init_rembg_session("birefnet-general")
    except (Exception, SystemExit) as exc:
        raise HTTPException(
            status_code=503,
            detail="Background removal model unavailable. Install rembg backend (e.g. onnxruntime).",
        ) from exc

    request.app.state.rembg_session = session
    return session


async def get_db() -> AsyncIterator[AsyncSession]:
    async for session in get_db_session():
        yield session
