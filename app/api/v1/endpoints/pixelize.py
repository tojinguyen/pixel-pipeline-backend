from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_s3_client
from app.core.exceptions import ImageProcessingError, StorageError
from app.models.image import DownscaledFile, PixelizedFile
from app.schemas.pixelize import (
    SinglePixelizeRequest,
    MultiplePixelizeRequest,
    PixelizedFileResponse,
    MultiplePixelizedFileResponse,
)
from app.services.image_service import build_storage_key
from app.services.pixelize_service import build_pixelized_filename, pixelize_image_async
from app.services.storage_service import download_file_async, get_file_url, upload_file_async

router = APIRouter(prefix="/pixelize")

async def _store_pixelized_file(
    db: AsyncSession,
    s3_client,
    source_record: DownscaledFile,
    output_bytes: bytes,
    num_colors: int,
) -> PixelizedFileResponse:
    output_filename = build_pixelized_filename(source_record.filename, num_colors)
    object_key = build_storage_key(output_filename, "processed/pixelized")
    
    await upload_file_async(output_bytes, object_key, "image/png", s3_client)

    record = PixelizedFile(
        source_file_id=source_record.id,
        source_type="downscaled",
        filename=output_filename,
        s3_key=object_key,
        url=get_file_url(object_key),
        content_type="image/png",
        num_colors=num_colors,
        file_size=len(output_bytes),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return PixelizedFileResponse(
        id=record.id,
        filename=record.filename,
        url=record.url,
        source_file_id=record.source_file_id,
        num_colors=record.num_colors,
        status="stored",
    )

@router.post("/image", response_model=PixelizedFileResponse)
async def pixelize_image(
    payload: SinglePixelizeRequest,
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
) -> PixelizedFileResponse:
    result = await db.execute(select(DownscaledFile).where(DownscaledFile.id == payload.file_id))
    source_record = result.scalar_one_or_none()
    
    if source_record is None:
        raise HTTPException(status_code=404, detail="Source file not found in downscaled_files")

    try:
        source_bytes = await download_file_async(source_record.s3_key, s3_client)
        pixelize_result = await pixelize_image_async(
            input_bytes=source_bytes,
            num_colors=payload.num_colors,
        )
        return await _store_pixelized_file(
            db=db,
            s3_client=s3_client,
            source_record=source_record,
            output_bytes=pixelize_result.image_bytes,
            num_colors=pixelize_result.num_colors,
        )
    except (StorageError, ImageProcessingError) as exc:
        status_code = 400 if isinstance(exc, ImageProcessingError) else 500
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

@router.post("/images", response_model=MultiplePixelizedFileResponse)
async def pixelize_images(
    payload: MultiplePixelizeRequest,
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
) -> MultiplePixelizedFileResponse:
    stored_files: list[PixelizedFileResponse] = []
    failed_files: list[str] = []

    for file_id in payload.file_ids:
        result = await db.execute(select(DownscaledFile).where(DownscaledFile.id == file_id))
        source_record = result.scalar_one_or_none()
        
        if source_record is None:
            failed_files.append(str(file_id))
            continue

        try:
            source_bytes = await download_file_async(source_record.s3_key, s3_client)
            pixelize_result = await pixelize_image_async(
                input_bytes=source_bytes,
                num_colors=payload.num_colors,
            )
            response = await _store_pixelized_file(
                db=db,
                s3_client=s3_client,
                source_record=source_record,
                output_bytes=pixelize_result.image_bytes,
                num_colors=pixelize_result.num_colors,
            )
            stored_files.append(response)
        except (StorageError, ImageProcessingError):
            failed_files.append(str(file_id))

    return MultiplePixelizedFileResponse(
        files=stored_files,
        failed=failed_files,
        status="completed" if not failed_files else "partial_success",
    )
