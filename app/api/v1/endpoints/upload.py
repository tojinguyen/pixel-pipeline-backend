from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_rembg_session, get_s3_client
from app.core.exceptions import ImageProcessingError, StorageError
from app.models.image import NoBgFile, OriginalFile
from app.schemas.image import (
    ImageUploadResponse,
    MultipleImageUploadResponse,
    MultipleNoBgImageResponse,
    NoBgImageResponse,
)
from app.services.image_service import (
    build_nobg_filename,
    build_storage_key,
    remove_background_async,
)
from app.services.storage_service import get_file_url, upload_file_async


router = APIRouter(prefix="/upload")


def _safe_filename(filename: str | None, fallback: str = "image.png") -> str:
    return filename or fallback


def _validate_image_content_type(content_type: str | None) -> None:
    if not content_type or not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")


@router.post("/image", response_model=ImageUploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
) -> ImageUploadResponse:
    _validate_image_content_type(file.content_type)
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file provided")

    filename = _safe_filename(file.filename)
    content_type = file.content_type or "image/png"
    object_key = build_storage_key(filename, "original")

    try:
        await upload_file_async(file_bytes, object_key, content_type, s3_client)
        record = OriginalFile(
            filename=filename,
            s3_key=object_key,
            url=get_file_url(object_key),
            content_type=content_type,
            file_size=len(file_bytes),
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return ImageUploadResponse(
            id=record.id,
            filename=filename,
            url=record.url,
            status="stored",
        )
    except StorageError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/images", response_model=MultipleImageUploadResponse)
async def upload_multiple_images(
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
) -> MultipleImageUploadResponse:
    saved_files: list[ImageUploadResponse] = []
    failed_files: list[str] = []

    for file in files:
        if file.content_type and not file.content_type.startswith("image/"):
            failed_files.append(_safe_filename(file.filename))
            continue

        file_bytes = await file.read()
        filename = _safe_filename(file.filename)

        if not file_bytes:
            failed_files.append(filename)
            continue

        try:
            object_key = build_storage_key(filename, "original")
            await upload_file_async(file_bytes, object_key, file.content_type or "image/png", s3_client)
            record = OriginalFile(
                filename=filename,
                s3_key=object_key,
                url=get_file_url(object_key),
                content_type=file.content_type or "image/png",
                file_size=len(file_bytes),
            )
            db.add(record)
            await db.commit()
            await db.refresh(record)
            saved_files.append(
                ImageUploadResponse(
                    id=record.id,
                    filename=filename,
                    url=record.url,
                    status="stored",
                )
            )
        except StorageError:
            await db.rollback()
            failed_files.append(filename)

    return MultipleImageUploadResponse(
        files=saved_files,
        failed=failed_files,
        status="completed" if not failed_files else "partial_success",
    )
