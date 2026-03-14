from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_s3_client
from app.core.cleanup import CleanupError
from app.core.exceptions import StorageError
from app.models.image import CleanupFile, PixelizedFile
from app.schemas.cleanup import (
    CleanupRequest,
    CleanupBatchRequest,
    CleanupFileResponse,
    MultipleCleanupFileResponse,
)
from app.services.cleanup_service import build_cleanup_filename, cleanup_image_async
from app.services.image_service import build_storage_key
from app.services.storage_service import download_file_async, get_file_url, upload_file_async


router = APIRouter(prefix="/cleanup")


@router.post("/", response_model=CleanupFileResponse)
async def cleanup_image(
    payload: CleanupRequest,
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
) -> CleanupFileResponse:
    source_record, source_type = await _resolve_source_record(db, payload.file_id)
    if source_record is None:
        raise HTTPException(status_code=404, detail="Source file not found")

    try:
        source_bytes = await download_file_async(source_record.s3_key, s3_client)
        cleanup_result = await cleanup_image_async(
            input_bytes=source_bytes,
            kernel_size=payload.kernel_size,
            alpha_threshold=payload.alpha_threshold,
            iterations=payload.iterations,
        )
        return await _store_cleanup_file(
            db=db,
            s3_client=s3_client,
            source_record=source_record,
            source_type=source_type,
            output_bytes=cleanup_result.image_bytes,
            kernel_size=cleanup_result.kernel_size,
            alpha_threshold=cleanup_result.alpha_threshold,
            iterations=cleanup_result.iterations,
        )
    except (StorageError, CleanupError) as exc:
        status_code = 400 if isinstance(exc, CleanupError) else 500
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.post("/batch", response_model=MultipleCleanupFileResponse)
async def cleanup_images_batch(
    payload: CleanupBatchRequest,
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
) -> MultipleCleanupFileResponse:
    stored_files: list[CleanupFileResponse] = []
    failed_files: list[str] = []

    for file_id in payload.file_ids:
        source_record, source_type = await _resolve_source_record(db, file_id)
        if source_record is None:
            failed_files.append(str(file_id))
            continue

        try:
            source_bytes = await download_file_async(source_record.s3_key, s3_client)
            cleanup_result = await cleanup_image_async(
                input_bytes=source_bytes,
                kernel_size=payload.kernel_size,
                alpha_threshold=payload.alpha_threshold,
                iterations=payload.iterations,
            )
            response = await _store_cleanup_file(
                db=db,
                s3_client=s3_client,
                source_record=source_record,
                source_type=source_type,
                output_bytes=cleanup_result.image_bytes,
                kernel_size=cleanup_result.kernel_size,
                alpha_threshold=cleanup_result.alpha_threshold,
                iterations=cleanup_result.iterations,
            )
            stored_files.append(response)
        except (StorageError, CleanupError):
            failed_files.append(str(file_id))

    return MultipleCleanupFileResponse(
        files=stored_files,
        failed=failed_files,
        status="completed" if not failed_files else "partial_success",
    )


async def _resolve_source_record(
    db: AsyncSession,
    file_id: UUID,
) -> tuple[PixelizedFile | None, str | None]:
    pixelized_result = await db.execute(select(PixelizedFile).where(PixelizedFile.id == file_id))
    pixelized_file = pixelized_result.scalar_one_or_none()
    if pixelized_file is not None:
        return pixelized_file, "pixelized"

    return None, None


async def _store_cleanup_file(
    db: AsyncSession,
    s3_client,
    source_record: PixelizedFile,
    source_type: str,
    output_bytes: bytes,
    kernel_size: int,
    alpha_threshold: int,
    iterations: int,
) -> CleanupFileResponse:
    output_filename = build_cleanup_filename(
        source_record.filename,
        kernel_size,
        alpha_threshold,
        iterations,
    )
    object_key = build_storage_key(output_filename, "processed/cleanup")

    await upload_file_async(output_bytes, object_key, "image/png", s3_client)

    record = CleanupFile(
        source_file_id=source_record.id,
        source_type=source_type,
        filename=output_filename,
        s3_key=object_key,
        url=get_file_url(object_key),
        content_type="image/png",
        kernel_size=kernel_size,
        alpha_threshold=alpha_threshold,
        iterations=iterations,
        file_size=len(output_bytes),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return CleanupFileResponse(
        id=record.id,
        filename=record.filename,
        url=record.url,
        source_file_id=record.source_file_id,
        source_type=record.source_type,
        kernel_size=record.kernel_size,
        alpha_threshold=record.alpha_threshold,
        iterations=record.iterations,
        status="stored",
    )