import io
import zipfile
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_s3_client
from app.core.exceptions import StorageError
from app.core.pixelize import PixelizationError
from app.models.image import DownscaledFile, NoBgFile, OriginalFile, PixelizedFile
from app.schemas.pixelize import (
    MultiplePixelizedFileResponse,
    PixelizeByIdRequest,
    PixelizeByIdsRequest,
    PixelizedFileResponse,
)
from app.services.image_service import build_storage_key
from app.services.pixelize_service import build_pixelized_filename, pixelize_image_async
from app.services.storage_service import download_file_async, get_file_url, upload_file_async

router = APIRouter(prefix="/pixelize")


def _validate_image_content_type(content_type: str | None) -> None:
    if not content_type or not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")


@router.post("/image")
async def pixelize_single_image(
    file: UploadFile = File(...),
    mode: str = Form(default="auto"),
    num_colors: int | None = Form(default=None),
    palette_name: str | None = Form(default=None),
) -> StreamingResponse:
    _validate_image_content_type(file.content_type)
    input_bytes = await file.read()
    if not input_bytes:
        raise HTTPException(status_code=400, detail="Empty file provided")

    try:
        pixelize_result = await pixelize_image_async(
            input_bytes=input_bytes,
            mode=mode,
            num_colors=num_colors,
            palette_name=palette_name,
        )
    except PixelizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    output_filename = build_pixelized_filename(
        file.filename,
        pixelize_result.mode,
        pixelize_result.palette_name,
        pixelize_result.num_colors,
    )
    
    return StreamingResponse(
        io.BytesIO(pixelize_result.image_bytes),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="{output_filename}"'},
    )


@router.post("/images")
async def pixelize_multiple_images(
    files: list[UploadFile] = File(...),
    mode: str = Form(default="auto"),
    num_colors: int | None = Form(default=None),
    palette_name: str | None = Form(default=None),
) -> StreamingResponse:
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file in files:
            _validate_image_content_type(file.content_type)
            input_bytes = await file.read()
            if not input_bytes:
                continue

            try:
                pixelize_result = await pixelize_image_async(
                    input_bytes=input_bytes,
                    mode=mode,
                    num_colors=num_colors,
                    palette_name=palette_name,
                )
                output_filename = build_pixelized_filename(
                    file.filename,
                    pixelize_result.mode,
                    pixelize_result.palette_name,
                    pixelize_result.num_colors,
                )
                zip_file.writestr(output_filename, pixelize_result.image_bytes)
            except PixelizationError:
                continue

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="images_pixelized.zip"'},
    )


@router.post("/by-id", response_model=PixelizedFileResponse)
async def pixelize_by_id(
    payload: PixelizeByIdRequest,
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
) -> PixelizedFileResponse:
    source_record, source_type = await _resolve_source_record(db, payload.file_id)
    if source_record is None:
        raise HTTPException(status_code=404, detail="Source file not found")

    try:
        source_bytes = await download_file_async(source_record.s3_key, s3_client)
        pixelize_result = await pixelize_image_async(
            input_bytes=source_bytes,
            mode=payload.mode,
            num_colors=payload.num_colors,
            palette_name=payload.palette_name,
        )
        return await _store_pixelized_file(
            db=db,
            s3_client=s3_client,
            source_record=source_record,
            source_type=source_type,
            output_bytes=pixelize_result.image_bytes,
            mode=pixelize_result.mode,
            num_colors=pixelize_result.num_colors,
            palette_name=pixelize_result.palette_name,
        )
    except (StorageError, PixelizationError) as exc:
        status_code = 400 if isinstance(exc, PixelizationError) else 500
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.post("/by-ids", response_model=MultiplePixelizedFileResponse)
async def pixelize_by_ids(
    payload: PixelizeByIdsRequest,
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
) -> MultiplePixelizedFileResponse:
    stored_files: list[PixelizedFileResponse] = []
    failed_files: list[str] = []

    for file_id in payload.file_ids:
        source_record, source_type = await _resolve_source_record(db, file_id)
        if source_record is None:
            failed_files.append(str(file_id))
            continue

        try:
            source_bytes = await download_file_async(source_record.s3_key, s3_client)
            pixelize_result = await pixelize_image_async(
                input_bytes=source_bytes,
                mode=payload.mode,
                num_colors=payload.num_colors,
                palette_name=payload.palette_name,
            )
            response = await _store_pixelized_file(
                db=db,
                s3_client=s3_client,
                source_record=source_record,
                source_type=source_type,
                output_bytes=pixelize_result.image_bytes,
                mode=pixelize_result.mode,
                num_colors=pixelize_result.num_colors,
                palette_name=pixelize_result.palette_name,
            )
            stored_files.append(response)
        except (StorageError, PixelizationError):
            failed_files.append(str(file_id))

    return MultiplePixelizedFileResponse(
        files=stored_files,
        failed=failed_files,
        status="completed" if not failed_files else "partial_success",
    )


async def _resolve_source_record(
    db: AsyncSession,
    file_id: UUID,
) -> tuple[OriginalFile | NoBgFile | DownscaledFile | None, str | None]:
    
    # Check Downscaled first, as it's the most common direct predecessor
    downscaled_result = await db.execute(select(DownscaledFile).where(DownscaledFile.id == file_id))
    downscaled_file = downscaled_result.scalar_one_or_none()
    if downscaled_file is not None:
        return downscaled_file, "downscaled"

    nobg_result = await db.execute(select(NoBgFile).where(NoBgFile.id == file_id))
    nobg_file = nobg_result.scalar_one_or_none()
    if nobg_file is not None:
        return nobg_file, "nobg"

    original_result = await db.execute(select(OriginalFile).where(OriginalFile.id == file_id))
    original_file = original_result.scalar_one_or_none()
    if original_file is not None:
        return original_file, "original"

    return None, None


async def _store_pixelized_file(
    db: AsyncSession,
    s3_client,
    source_record: OriginalFile | NoBgFile | DownscaledFile,
    source_type: str,
    output_bytes: bytes,
    mode: str,
    num_colors: int | None,
    palette_name: str | None,
) -> PixelizedFileResponse:
    output_filename = build_pixelized_filename(source_record.filename, mode, palette_name, num_colors)
    object_key = build_storage_key(output_filename, "processed/pixelized")
    
    await upload_file_async(output_bytes, object_key, "image/png", s3_client)

    record = PixelizedFile(
        source_file_id=source_record.id,
        source_type=source_type,
        filename=output_filename,
        s3_key=object_key,
        url=get_file_url(object_key),
        content_type="image/png",
        mode=mode,
        num_colors=num_colors,
        palette_name=palette_name,
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
        source_type=record.source_type,
        mode=record.mode,
        num_colors=record.num_colors,
        palette_name=record.palette_name,
        status="stored",
    )