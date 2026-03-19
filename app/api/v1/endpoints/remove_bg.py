import io
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_rembg_session, get_s3_client
from app.core.exceptions import ImageProcessingError, StorageError
from app.models.image import NoBgFile, OriginalFile
from app.schemas.image import MultipleNoBgImageResponse, MultipleRemoveBgRequest, NoBgImageResponse, SingleRemoveBgRequest
from app.services.downscale_service import downscale_image_async
from app.services.image_service import build_nobg_filename, build_storage_key, remove_background_async
from app.services.storage_service import download_file_async, get_file_url, upload_file_async


router = APIRouter(prefix="/remove-bg")

_SUPPORTED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def _validate_image(file: UploadFile) -> None:
    if file.content_type not in _SUPPORTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{file.content_type}'. Accepted: png, jpeg, webp, gif.",
        )


@router.post("/image", response_model=NoBgImageResponse)
async def remove_bg_single_image(
    request: SingleRemoveBgRequest,
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
    rembg_session=Depends(get_rembg_session),
) -> NoBgImageResponse:
    result = await db.execute(select(OriginalFile).where(OriginalFile.id == request.original_file_id))
    original_file = result.scalar_one_or_none()

    if original_file is None:
        raise HTTPException(status_code=404, detail="Original file not found")

    try:
        input_bytes = await download_file_async(original_file.s3_key, s3_client)
        downscale_result = await downscale_image_async(input_bytes, request.target_width, request.target_height)
        output_bytes = await remove_background_async(downscale_result.image_bytes, rembg_session)
        output_filename = build_nobg_filename(original_file.filename)
        object_key = build_storage_key(output_filename, "processed/nobg")
        await upload_file_async(output_bytes, object_key, "image/png", s3_client)

        record = NoBgFile(
            original_file_id=request.original_file_id,
            filename=output_filename,
            s3_key=object_key,
            url=get_file_url(object_key),
            content_type="image/png",
            target_width=downscale_result.output_width,
            target_height=downscale_result.output_height,
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
            target_width=record.target_width,
            target_height=record.target_height,
            status="stored",
        )
    except (ImageProcessingError, StorageError) as exc:
        import traceback
        traceback.print_exc()
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        import traceback
        traceback.print_exc()
        await db.rollback()
        raise HTTPException(status_code=500, detail="Image processing failed") from exc


@router.post(
    "/image-direct",
    summary="Upload + remove background + downscale -> PNG",
    response_class=StreamingResponse,
)
async def remove_bg_direct_image(
    file: UploadFile = File(..., description="Source image to process"),
    target_width: int = Form(..., gt=0),
    target_height: int = Form(..., gt=0),
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
    rembg_session=Depends(get_rembg_session),
) -> StreamingResponse:
    """
    Accept image upload directly, persist the original file, then process
    downscale + remove background, persist result, and stream PNG back.
    """
    _validate_image(file)

    filename = file.filename or "image.png"
    content_type = file.content_type or "image/png"

    try:
        input_bytes = await file.read()
        if not input_bytes:
            raise HTTPException(status_code=400, detail="Empty file provided")

        original_object_key = build_storage_key(filename, "original")
        await upload_file_async(input_bytes, original_object_key, content_type, s3_client)

        original_record = OriginalFile(
            filename=filename,
            s3_key=original_object_key,
            url=get_file_url(original_object_key),
            content_type=content_type,
            file_size=len(input_bytes),
        )
        db.add(original_record)
        await db.commit()
        await db.refresh(original_record)

        downscale_result = await downscale_image_async(input_bytes, target_width, target_height)
        output_bytes = await remove_background_async(downscale_result.image_bytes, rembg_session)
        output_filename = build_nobg_filename(filename)
        output_object_key = build_storage_key(output_filename, "processed/nobg")
        await upload_file_async(output_bytes, output_object_key, "image/png", s3_client)

        nobg_record = NoBgFile(
            original_file_id=original_record.id,
            filename=output_filename,
            s3_key=output_object_key,
            url=get_file_url(output_object_key),
            content_type="image/png",
            target_width=downscale_result.output_width,
            target_height=downscale_result.output_height,
            file_size=len(output_bytes),
        )
        db.add(nobg_record)
        await db.commit()
        await db.refresh(nobg_record)

        return StreamingResponse(
            io.BytesIO(output_bytes),
            media_type="image/png",
            headers={
                "Content-Disposition": f'attachment; filename="{nobg_record.filename}"',
                "X-Original-File-Id": str(original_record.id),
                "X-NoBg-File-Id": str(nobg_record.id),
            },
        )
    except HTTPException:
        raise
    except ImageProcessingError as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StorageError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        import traceback
        traceback.print_exc()
        await db.rollback()
        raise HTTPException(status_code=500, detail="Image processing failed") from exc


@router.post("/images", response_model=MultipleNoBgImageResponse)
async def remove_bg_multiple_images(
    request: MultipleRemoveBgRequest,
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
    rembg_session=Depends(get_rembg_session),
) -> MultipleNoBgImageResponse:
    saved_files: list[NoBgImageResponse] = []
    failed_files: list[str] = []

    for file_id in request.original_file_ids:
        result = await db.execute(select(OriginalFile).where(OriginalFile.id == file_id))
        original_file = result.scalar_one_or_none()

        if original_file is None:
            failed_files.append(str(file_id))
            continue

        try:
            input_bytes = await download_file_async(original_file.s3_key, s3_client)
            downscale_result = await downscale_image_async(input_bytes, request.target_width, request.target_height)
            output_bytes = await remove_background_async(downscale_result.image_bytes, rembg_session)
            output_filename = build_nobg_filename(original_file.filename)
            object_key = build_storage_key(output_filename, "processed/nobg")
            await upload_file_async(output_bytes, object_key, "image/png", s3_client)

            record = NoBgFile(
                original_file_id=file_id,
                filename=output_filename,
                s3_key=object_key,
                url=get_file_url(object_key),
                content_type="image/png",
                target_width=downscale_result.output_width,
                target_height=downscale_result.output_height,
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
                    target_width=record.target_width,
                    target_height=record.target_height,
                    status="stored",
                )
            )
        except (ImageProcessingError, StorageError):
            await db.rollback()
            failed_files.append(str(file_id))

    return MultipleNoBgImageResponse(
        files=saved_files,
        failed=failed_files,
        status="completed" if not failed_files else "partial_success",
    )
