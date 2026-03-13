from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_rembg_session, get_s3_client
from app.core.exceptions import ImageProcessingError, StorageError
from app.models.image import NoBgFile, OriginalFile
from app.schemas.image import MultipleNoBgImageResponse, MultipleRemoveBgRequest, NoBgImageResponse, SingleRemoveBgRequest
from app.services.image_service import build_nobg_filename, build_storage_key, remove_background_async
from app.services.storage_service import download_file_async, get_file_url, upload_file_async


router = APIRouter(prefix="/remove-bg")


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
        output_bytes = await remove_background_async(input_bytes, rembg_session)
        output_filename = build_nobg_filename(original_file.filename)
        object_key = build_storage_key(output_filename, "processed/nobg")
        await upload_file_async(output_bytes, object_key, "image/png", s3_client)

        record = NoBgFile(
            original_file_id=request.original_file_id,
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
            output_bytes = await remove_background_async(input_bytes, rembg_session)
            output_filename = build_nobg_filename(original_file.filename)
            object_key = build_storage_key(output_filename, "processed/nobg")
            await upload_file_async(output_bytes, object_key, "image/png", s3_client)

            record = NoBgFile(
                original_file_id=file_id,
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
            failed_files.append(str(file_id))

    return MultipleNoBgImageResponse(
        files=saved_files,
        failed=failed_files,
        status="completed" if not failed_files else "partial_success",
    )
