from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_s3_client
from app.core.exceptions import ImageProcessingError, StorageError
from app.models.image import DownscaledFile, NoBgFile
from app.schemas.downscale import (
    SingleDownscaleRequest,
    MultipleDownscaleRequest,
    DownscaledFileResponse,
    MultipleDownscaledFileResponse,
)
from app.services.downscale_service import (
    build_downscaled_filename,
    downscale_image_async,
)
from app.services.image_service import build_storage_key
from app.services.storage_service import download_file_async, get_file_url, upload_file_async

router = APIRouter(prefix="/downscale")

async def _store_downscaled_file(
    db: AsyncSession,
    s3_client,
    source_record: NoBgFile,
    output_bytes: bytes,
    target_width: int,
    target_height: int,
) -> DownscaledFileResponse:
    output_filename = build_downscaled_filename(source_record.filename, target_width, target_height)
    object_key = build_storage_key(output_filename, "processed/downscaled")
    await upload_file_async(output_bytes, object_key, "image/png", s3_client)

    record = DownscaledFile(
        source_file_id=source_record.id,
        source_type="nobg",
        filename=output_filename,
        s3_key=object_key,
        url=get_file_url(object_key),
        content_type="image/png",
        target_width=target_width,
        target_height=target_height,
        file_size=len(output_bytes),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return DownscaledFileResponse(
        id=record.id,
        filename=record.filename,
        url=record.url,
        source_file_id=record.source_file_id,
        target_width=record.target_width,
        target_height=record.target_height,
        status="stored",
    )

@router.post("/image", response_model=DownscaledFileResponse)
async def downscale_image(
    payload: SingleDownscaleRequest,
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
) -> DownscaledFileResponse:
    result = await db.execute(select(NoBgFile).where(NoBgFile.id == payload.file_id))
    source_record = result.scalar_one_or_none()
    
    if source_record is None:
        raise HTTPException(status_code=404, detail="Source file not found in nobg_files")

    try:
        source_bytes = await download_file_async(source_record.s3_key, s3_client)
        downscale_result = await downscale_image_async(
            source_bytes,
            payload.target_width,
            payload.target_height,
        )
        return await _store_downscaled_file(
            db=db,
            s3_client=s3_client,
            source_record=source_record,
            output_bytes=downscale_result.image_bytes,
            target_width=downscale_result.output_width,
            target_height=downscale_result.output_height,
        )
    except (StorageError, ImageProcessingError) as exc:
        status_code = 400 if isinstance(exc, ImageProcessingError) else 500
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

@router.post("/images", response_model=MultipleDownscaledFileResponse)
async def downscale_images(
    payload: MultipleDownscaleRequest,
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
) -> MultipleDownscaledFileResponse:
    stored_files: list[DownscaledFileResponse] = []
    failed_files: list[str] = []

    for file_id in payload.file_ids:
        result = await db.execute(select(NoBgFile).where(NoBgFile.id == file_id))
        source_record = result.scalar_one_or_none()
        
        if source_record is None:
            failed_files.append(str(file_id))
            continue

        try:
            source_bytes = await download_file_async(source_record.s3_key, s3_client)
            downscale_result = await downscale_image_async(
                source_bytes,
                payload.target_width,
                payload.target_height,
            )
            response = await _store_downscaled_file(
                db=db,
                s3_client=s3_client,
                source_record=source_record,
                output_bytes=downscale_result.image_bytes,
                target_width=downscale_result.output_width,
                target_height=downscale_result.output_height,
            )
            stored_files.append(response)
        except (StorageError, ImageProcessingError):
            failed_files.append(str(file_id))

    return MultipleDownscaledFileResponse(
        files=stored_files,
        failed=failed_files,
        status="completed" if not failed_files else "partial_success",
    )

