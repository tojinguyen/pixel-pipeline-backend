from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_rembg_session, get_s3_client
from app.core.exceptions import ImageProcessingError, StorageError
from app.models.image import NoBgFile, OriginalFile
from app.schemas.image import MultipleNoBgImageResponse, NoBgImageResponse
from app.services.image_service import build_nobg_filename, build_storage_key, remove_background_async
from app.services.storage_service import get_file_url, upload_file_async


router = APIRouter(prefix="/remove-bg")


def _safe_filename(filename: str | None, fallback: str = "image.png") -> str:
    return filename or fallback


def _validate_image_content_type(content_type: str | None) -> None:
    if not content_type or not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")


@router.post("/image", response_model=NoBgImageResponse)
async def remove_bg_single_image(
    file: UploadFile = File(...),
    original_file_id: UUID | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
    rembg_session=Depends(get_rembg_session),
) -> NoBgImageResponse:
    _validate_image_content_type(file.content_type)

    input_bytes = await file.read()
    if not input_bytes:
        raise HTTPException(status_code=400, detail="Empty file provided")

    if original_file_id is not None:
        result = await db.execute(select(OriginalFile).where(OriginalFile.id == original_file_id))
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Original file not found")

    try:
        output_bytes = await remove_background_async(input_bytes, rembg_session)
        output_filename = build_nobg_filename(file.filename)
        object_key = build_storage_key(output_filename, "processed/nobg")
        await upload_file_async(output_bytes, object_key, "image/png", s3_client)

        record = NoBgFile(
            original_file_id=original_file_id,
            filename=output_filename,
            s3_key=object_key,
            url=get_file_url(object_key),
            content_type="image/png",
            file_size=len(output_bytes),
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return NoBgImageResponse(
            id=record.id,
            filename=record.filename,
            url=record.url,
            original_file_id=record.original_file_id,
            status="stored",
        )
    except (ImageProcessingError, StorageError) as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Image processing failed") from exc


@router.post("/images", response_model=MultipleNoBgImageResponse)
async def remove_bg_multiple_images(
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
    rembg_session=Depends(get_rembg_session),
) -> MultipleNoBgImageResponse:
    saved_files: list[NoBgImageResponse] = []
    failed_files: list[str] = []

    for file in files:
        filename = _safe_filename(file.filename)
        if file.content_type and not file.content_type.startswith("image/"):
            failed_files.append(filename)
            continue

        input_bytes = await file.read()
        if not input_bytes:
            failed_files.append(filename)
            continue

        try:
            output_bytes = await remove_background_async(input_bytes, rembg_session)
            output_filename = build_nobg_filename(file.filename)
            object_key = build_storage_key(output_filename, "processed/nobg")
            await upload_file_async(output_bytes, object_key, "image/png", s3_client)

            record = NoBgFile(
                original_file_id=None,
                filename=output_filename,
                s3_key=object_key,
                url=get_file_url(object_key),
                content_type="image/png",
                file_size=len(output_bytes),
            )
            db.add(record)
            await db.commit()
            await db.refresh(record)
            saved_files.append(
                NoBgImageResponse(
                    id=record.id,
                    filename=record.filename,
                    url=record.url,
                    original_file_id=record.original_file_id,
                    status="stored",
                )
            )
        except (ImageProcessingError, StorageError):
            await db.rollback()
            failed_files.append(filename)

    return MultipleNoBgImageResponse(
        files=saved_files,
        failed=failed_files,
        status="completed" if not failed_files else "partial_success",
    )
