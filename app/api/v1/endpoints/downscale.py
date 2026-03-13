import io
import zipfile
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_s3_client
from app.core.exceptions import ImageProcessingError, StorageError
from app.models.image import DownscaledFile, NoBgFile, OriginalFile
from app.schemas.downscale import (
    DownscaleByIdRequest,
    DownscaleByIdsRequest,
    DownscaledFileResponse,
    MultipleDownscaledFileResponse,
)
from app.services.downscale_service import build_downscaled_filename, downscale_image_async
from app.services.image_service import build_storage_key
from app.services.storage_service import download_file_async, get_file_url, upload_file_async


router = APIRouter(prefix="/downscale")


def _safe_filename(filename: str | None, fallback: str = "image.png") -> str:
    return filename or fallback


def _validate_image_content_type(content_type: str | None) -> None:
    if not content_type or not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")


@router.post("/image")
async def downscale_single_image(
    file: UploadFile = File(...),
    target_width: int = Form(..., gt=0, le=4096),
    target_height: int = Form(..., gt=0, le=4096),
) -> StreamingResponse:
    _validate_image_content_type(file.content_type)
    input_bytes = await file.read()
    if not input_bytes:
        raise HTTPException(status_code=400, detail="Empty file provided")

    try:
        output_bytes = await downscale_image_async(input_bytes, target_width, target_height)
    except ImageProcessingError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    output_filename = build_downscaled_filename(file.filename, target_width, target_height)
    return StreamingResponse(
        io.BytesIO(output_bytes),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="{output_filename}"'},
    )


@router.post("/images")
async def downscale_multiple_images(
    files: list[UploadFile] = File(...),
    target_width: int = Form(..., gt=0, le=4096),
    target_height: int = Form(..., gt=0, le=4096),
) -> StreamingResponse:
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file in files:
            _validate_image_content_type(file.content_type)
            input_bytes = await file.read()
            if not input_bytes:
                continue

            try:
                output_bytes = await downscale_image_async(input_bytes, target_width, target_height)
                output_filename = build_downscaled_filename(file.filename, target_width, target_height)
                zip_file.writestr(output_filename, output_bytes)
            except ImageProcessingError:
                continue

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="images_downscaled.zip"'},
    )


@router.post("/by-id", response_model=DownscaledFileResponse)
async def downscale_by_id(
    payload: DownscaleByIdRequest,
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
) -> DownscaledFileResponse:
    source_record, source_type = await _resolve_source_record(db, payload.file_id)
    if source_record is None:
        raise HTTPException(status_code=404, detail="Source file not found")

    try:
        source_bytes = await download_file_async(source_record.s3_key, s3_client)
        output_bytes = await downscale_image_async(
            source_bytes,
            payload.target_width,
            payload.target_height,
        )
        return await _store_downscaled_file(
            db=db,
            s3_client=s3_client,
            source_record=source_record,
            source_type=source_type,
            output_bytes=output_bytes,
            target_width=payload.target_width,
            target_height=payload.target_height,
        )
    except (StorageError, ImageProcessingError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/by-ids", response_model=MultipleDownscaledFileResponse)
async def downscale_by_ids(
    payload: DownscaleByIdsRequest,
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
) -> MultipleDownscaledFileResponse:
    stored_files: list[DownscaledFileResponse] = []
    failed_files: list[str] = []

    for file_id in payload.file_ids:
        source_record, source_type = await _resolve_source_record(db, file_id)
        if source_record is None:
            failed_files.append(str(file_id))
            continue

        try:
            source_bytes = await download_file_async(source_record.s3_key, s3_client)
            output_bytes = await downscale_image_async(
                source_bytes,
                payload.target_width,
                payload.target_height,
            )
            response = await _store_downscaled_file(
                db=db,
                s3_client=s3_client,
                source_record=source_record,
                source_type=source_type,
                output_bytes=output_bytes,
                target_width=payload.target_width,
                target_height=payload.target_height,
            )
            stored_files.append(response)
        except (StorageError, ImageProcessingError):
            failed_files.append(str(file_id))

    return MultipleDownscaledFileResponse(
        files=stored_files,
        failed=failed_files,
        status="completed" if not failed_files else "partial_success",
    )


async def _resolve_source_record(
    db: AsyncSession,
    file_id: UUID,
) -> tuple[OriginalFile | NoBgFile | None, str | None]:
    original_result = await db.execute(select(OriginalFile).where(OriginalFile.id == file_id))
    original_file = original_result.scalar_one_or_none()
    if original_file is not None:
        return original_file, "original"

    nobg_result = await db.execute(select(NoBgFile).where(NoBgFile.id == file_id))
    nobg_file = nobg_result.scalar_one_or_none()
    if nobg_file is not None:
        return nobg_file, "nobg"

    return None, None


async def _store_downscaled_file(
    db: AsyncSession,
    s3_client,
    source_record: OriginalFile | NoBgFile,
    source_type: str,
    output_bytes: bytes,
    target_width: int,
    target_height: int,
) -> DownscaledFileResponse:
    output_filename = build_downscaled_filename(source_record.filename, target_width, target_height)
    object_key = build_storage_key(output_filename, "processed/downscaled")
    await upload_file_async(output_bytes, object_key, "image/png", s3_client)

    record = DownscaledFile(
        source_file_id=source_record.id,
        source_type=source_type,
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
        source_type=record.source_type,
        target_width=record.target_width,
        target_height=record.target_height,
        status="stored",
    )