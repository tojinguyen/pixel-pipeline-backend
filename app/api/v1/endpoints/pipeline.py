import io
import zipfile
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_rembg_session, get_s3_client
from app.core.cleanup import CleanupError
from app.core.exceptions import ImageProcessingError, StorageError
from app.models.image import PipelineFile
from app.schemas.pipeline import MultiplePipelineResponse, PipelineFileResponse, PipelineParams
from app.services.pipeline_service import run_pipeline_async
from app.services.pixelize_service import DitherMethod
from app.services.storage_service import download_file_async


router = APIRouter(prefix="/pipeline")

_SUPPORTED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def _validate_image(file: UploadFile) -> None:
    if file.content_type not in _SUPPORTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{file.content_type}'. Accepted: png, jpeg, webp, gif.",
        )


@router.post(
    "/image",
    summary="Full pipeline — single image → PNG",
    response_class=StreamingResponse,
)
async def pipeline_single_image(
    file: UploadFile = File(..., description="Source image to process"),
    target_pixel_size: int = Form(default=64, ge=8, le=512),
    num_colors: int = Form(default=16, ge=1, le=256),
    dither_method: DitherMethod = Form(default=DitherMethod.ORDERED),
    dither_strength: float = Form(default=0.4, ge=0.0, le=1.0),
    alpha_threshold: int = Form(default=128, ge=0, le=255),
    min_component_size: int = Form(default=2, ge=1, le=20),
    add_outline: bool = Form(default=True),
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
    rembg_session=Depends(get_rembg_session),
) -> StreamingResponse:
    """
    Process a single image through the full pixel-art pipeline:
    **remove_bg → pixelize → cleanup**.

    Saves the result to S3 + DB and streams the PNG back to the client.
    """
    _validate_image(file)

    params = PipelineParams(
        target_pixel_size=target_pixel_size,
        num_colors=num_colors,
        dither_method=dither_method,
        dither_strength=dither_strength,
        alpha_threshold=alpha_threshold,
        min_component_size=min_component_size,
        add_outline=add_outline,
    )

    try:
        input_bytes = await file.read()
        result = await run_pipeline_async(
            input_bytes=input_bytes,
            original_filename=file.filename or "image.png",
            params=params,
            db=db,
            s3_client=s3_client,
            rembg_session=rembg_session,
        )
    except (ImageProcessingError, CleanupError) as exc:
        await db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StorageError as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        import traceback
        traceback.print_exc()
        await db.rollback()
        raise HTTPException(status_code=500, detail="Pipeline processing failed") from exc

    return StreamingResponse(
        io.BytesIO(result.image_bytes),
        media_type="image/png",
        headers={
            "Content-Disposition": f'attachment; filename="{result.record.filename}"',
            "X-Pipeline-File-Id": str(result.record.id),
        },
    )


@router.post(
    "/images",
    response_model=MultiplePipelineResponse,
    summary="Full pipeline — multiple images → ZIP",
)
async def pipeline_batch_images(
    files: list[UploadFile] = File(..., description="Source images to process"),
    target_pixel_size: int = Form(default=64, ge=8, le=512),
    num_colors: int = Form(default=16, ge=1, le=256),
    dither_method: DitherMethod = Form(default=DitherMethod.ORDERED),
    dither_strength: float = Form(default=0.4, ge=0.0, le=1.0),
    alpha_threshold: int = Form(default=128, ge=0, le=255),
    min_component_size: int = Form(default=2, ge=1, le=20),
    add_outline: bool = Form(default=True),
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
    rembg_session=Depends(get_rembg_session),
) -> StreamingResponse:
    """
    Process multiple images through the full pixel-art pipeline:
    **remove_bg → pixelize → cleanup**.

    Each image is processed sequentially. Results are saved to S3 + DB and
    returned as a single ZIP archive.
    """
    if not files:
        raise HTTPException(status_code=422, detail="At least one file is required.")

    for f in files:
        _validate_image(f)

    params = PipelineParams(
        target_pixel_size=target_pixel_size,
        num_colors=num_colors,
        dither_method=dither_method,
        dither_strength=dither_strength,
        alpha_threshold=alpha_threshold,
        min_component_size=min_component_size,
        add_outline=add_outline,
    )

    processed: list[PipelineFileResponse] = []
    failed: list[str] = []
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for upload in files:
            original_name = upload.filename or "image.png"
            try:
                input_bytes = await upload.read()
                result = await run_pipeline_async(
                    input_bytes=input_bytes,
                    original_filename=original_name,
                    params=params,
                    db=db,
                    s3_client=s3_client,
                    rembg_session=rembg_session,
                )
                zf.writestr(result.record.filename, result.image_bytes)
                processed.append(PipelineFileResponse.model_validate(result.record))
            except Exception:
                import traceback
                traceback.print_exc()
                await db.rollback()
                failed.append(original_name)

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="pixel_art_batch.zip"',
            "X-Pipeline-Processed": str(len(processed)),
            "X-Pipeline-Failed": str(len(failed)),
        },
    )


@router.get(
    "/download",
    summary="Download all pipeline results as ZIP",
    response_class=StreamingResponse,
)
async def download_all_pipeline_results(
    db: AsyncSession = Depends(get_db),
    s3_client=Depends(get_s3_client),
) -> StreamingResponse:
    """
    Download every image that has been processed by the pipeline
    (`/pipeline/image` or `/pipeline/images`) as a single ZIP file.

    Files are fetched directly from S3.
    """
    result = await db.execute(select(PipelineFile).order_by(PipelineFile.created_at.asc()))
    records: list[PipelineFile] = list(result.scalars().all())

    if not records:
        raise HTTPException(status_code=404, detail="No pipeline results found.")

    zip_buffer = io.BytesIO()
    failed: list[str] = []

    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for record in records:
            try:
                file_bytes = await download_file_async(record.s3_key, s3_client)
                zf.writestr(record.filename, file_bytes)
            except Exception:
                failed.append(record.filename)

    if failed:
        # Log but don't fail — return whatever we got
        print(f"[pipeline/download] Failed to fetch {len(failed)} file(s): {failed}")

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="pipeline_results.zip"',
            "X-Total-Files": str(len(records)),
            "X-Failed-Files": str(len(failed)),
        },
    )
