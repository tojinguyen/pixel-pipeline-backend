"""
Pipeline service: orchestrates remove_bg → pixelize → cleanup in sequence,
then uploads the final PNG to S3 and persists a PipelineFile record in the DB.
"""

import io
import os
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.image import PipelineFile
from app.schemas.pipeline import PipelineParams
from app.services.cleanup_service import cleanup_image_async
from app.services.image_service import build_storage_key, remove_background_async
from app.services.pixelize_service import pixelize_image_async
from app.services.storage_service import get_file_url, upload_file_async


@dataclass
class PipelineResult:
    image_bytes: bytes
    record: PipelineFile


def _build_pipeline_filename(original_filename: str) -> str:
    """Generate an output filename that reflects the pipeline processing chain."""
    base = os.path.splitext(os.path.basename(original_filename))[0]
    if not base:
        base = "image"
    return f"{base}_pipeline.png"


async def run_pipeline_async(
    input_bytes: bytes,
    original_filename: str,
    params: PipelineParams,
    db: AsyncSession,
    s3_client,
    rembg_session,
) -> PipelineResult:
    """
    Execute the full pixel-art pipeline on raw image bytes, persist the result.

    Steps:
        1. remove_bg  — AI background removal + hard alpha binarization
        2. pixelize   — contrast-aware downscale, LAB color quantization, dithering
        3. cleanup    — CCL orphan removal + optional 1-px outline
        4. S3 upload + DB persist

    Args:
        input_bytes:       Raw bytes of the uploaded image.
        original_filename: Original filename from the upload (used for naming).
        params:            Pipeline configuration parameters.
        db:                Async SQLAlchemy session.
        s3_client:         Boto3 S3 client.
        rembg_session:     Pre-loaded rembg inference session.

    Returns:
        PipelineResult with the final PNG bytes and the persisted DB record.
    """
    # Step 1: Background removal
    nobg_bytes = await remove_background_async(input_bytes, rembg_session)

    # Step 2: Pixelization (downscale + color quantization + dithering)
    pixelize_result = await pixelize_image_async(
        input_bytes=nobg_bytes,
        num_colors=params.num_colors,
        target_size=params.target_pixel_size,
        dither_method=params.dither_method,
        dither_strength=params.dither_strength,
        rembg_session=None,  # already removed bg; skip internal re-removal
    )

    # Step 3: Cleanup (alpha binarization + CCL orphan removal + outline)
    cleanup_result = await cleanup_image_async(
        input_bytes=pixelize_result.image_bytes,
        alpha_threshold=params.alpha_threshold,
        min_component_size=params.min_component_size,
        add_outline=params.add_outline,
    )

    # Step 4: Upload to S3
    output_filename = _build_pipeline_filename(original_filename)
    object_key = build_storage_key(output_filename, "processed/pipeline")
    await upload_file_async(cleanup_result.image_bytes, object_key, "image/png", s3_client)

    # Step 5: Persist to DB
    record = PipelineFile(
        original_filename=original_filename,
        filename=output_filename,
        s3_key=object_key,
        url=get_file_url(object_key),
        content_type="image/png",
        file_size=len(cleanup_result.image_bytes),
        target_pixel_size=params.target_pixel_size,
        num_colors=params.num_colors,
        dither_method=params.dither_method.value,
        dither_strength=params.dither_strength,
        alpha_threshold=params.alpha_threshold,
        min_component_size=params.min_component_size,
        add_outline=params.add_outline,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return PipelineResult(image_bytes=cleanup_result.image_bytes, record=record)
