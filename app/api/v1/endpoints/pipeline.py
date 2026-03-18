from fastapi import APIRouter, File, UploadFile, Form, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import Response, StreamingResponse
from typing import List
import io
import zipfile
import asyncio

from app.api.dependencies import get_db, get_s3_client, get_rembg_session
from app.models.image import OriginalFile, NoBgFile, DownscaledFile, PixelizedFile, CleanupFile
from app.services.image_service import (
    build_nobg_filename,
    build_storage_key,
    remove_background_async
)
from app.services.downscale_service import (
    downscale_image_async,
    build_downscaled_filename
)
from app.services.pixelize_service import (
    DitherMethod,
    pixelize_image_async,
    build_pixelized_filename
)
from app.services.cleanup_service import (
    cleanup_image_async,
    build_cleanup_filename
)
from app.services.storage_service import (
    upload_file_async,
    get_file_url
)

router = APIRouter()

async def process_single_pipeline(
    file: UploadFile,
    downscale_width: int,
    downscale_height: int,
    num_colors: int,
    target_size: int,
    dither_method: DitherMethod,
    dither_strength: float,
    alpha_threshold: int,
    min_component_size: int,
    add_outline: bool,
    db: AsyncSession,
    s3_client,
    rembg_session
) -> bytes:
    """
    Executes the full pipeline for a single image, saving intermediate steps.
    Returns the final bytes of the cleaned up image.
    """
    file_bytes = await file.read()
    orig_filename = file.filename or "image.png"
    
    # ------------------
    # Step 1: Upload Original
    # ------------------
    orig_key = build_storage_key(orig_filename, "originals")
    await upload_file_async(file_bytes, orig_key, file.content_type or "image/png", s3_client)
    
    orig_record = OriginalFile(
        filename=orig_filename,
        s3_key=orig_key,
        url=get_file_url(orig_key),
        content_type=file.content_type,
        file_size=len(file_bytes)
    )
    db.add(orig_record)
    await db.commit()
    await db.refresh(orig_record)
    
    # ------------------
    # Step 2: Remove BG
    # ------------------
    nobg_bytes = await remove_background_async(file_bytes, rembg_session)
    nobg_filename = build_nobg_filename(orig_filename)
    nobg_key = build_storage_key(nobg_filename, "processed/nobg")
    await upload_file_async(nobg_bytes, nobg_key, "image/png", s3_client)
    
    nobg_record = NoBgFile(
        original_file_id=orig_record.id,
        filename=nobg_filename,
        s3_key=nobg_key,
        url=get_file_url(nobg_key),
        content_type="image/png",
        file_size=len(nobg_bytes)
    )
    db.add(nobg_record)
    await db.commit()
    await db.refresh(nobg_record)
    
    # ------------------
    # Step 3: Downscale
    # ------------------
    down_result = await downscale_image_async(
        input_bytes=nobg_bytes,
        target_width=downscale_width,
        target_height=downscale_height
    )
    down_filename = build_downscaled_filename(orig_filename, downscale_width, downscale_height)
    down_key = build_storage_key(down_filename, "processed/downscaled")
    await upload_file_async(down_result.image_bytes, down_key, "image/png", s3_client)
    
    down_record = DownscaledFile(
        source_file_id=nobg_record.id,
        source_type="nobg",
        filename=down_filename,
        s3_key=down_key,
        url=get_file_url(down_key),
        content_type="image/png",
        file_size=len(down_result.image_bytes),
        target_width=down_result.output_width,
        target_height=down_result.output_height
    )
    db.add(down_record)
    await db.commit()
    await db.refresh(down_record)

    # ------------------
    # Step 4: Pixelize
    # ------------------
    pix_result = await pixelize_image_async(
        input_bytes=down_result.image_bytes,
        num_colors=num_colors,
        target_size=target_size,
        dither_method=dither_method,
        dither_strength=dither_strength
    )
    pix_filename = build_pixelized_filename(orig_filename, num_colors)
    pix_key = build_storage_key(pix_filename, "processed/pixelized")
    await upload_file_async(pix_result.image_bytes, pix_key, "image/png", s3_client)
    
    pix_record = PixelizedFile(
        source_file_id=down_record.id,
        source_type="downscaled",
        filename=pix_filename,
        s3_key=pix_key,
        url=get_file_url(pix_key),
        content_type="image/png",
        file_size=len(pix_result.image_bytes),
        num_colors=pix_result.num_colors
    )
    db.add(pix_record)
    await db.commit()
    await db.refresh(pix_record)

    # ------------------
    # Step 5: Cleanup
    # ------------------
    clean_result = await cleanup_image_async(
        input_bytes=pix_result.image_bytes,
        alpha_threshold=alpha_threshold,
        min_component_size=min_component_size,
        add_outline=add_outline
    )
    clean_filename = build_cleanup_filename(orig_filename, alpha_threshold, min_component_size, add_outline)
    clean_key = build_storage_key(clean_filename, "processed/cleanup")
    await upload_file_async(clean_result.image_bytes, clean_key, "image/png", s3_client)
    
    clean_record = CleanupFile(
        source_file_id=pix_record.id,
        source_type="pixelized",
        filename=clean_filename,
        s3_key=clean_key,
        url=get_file_url(clean_key),
        content_type="image/png",
        file_size=len(clean_result.image_bytes),
        alpha_threshold=clean_result.alpha_threshold,
        min_component_size=clean_result.min_component_size,
        add_outline=clean_result.add_outline
    )
    db.add(clean_record)
    await db.commit()
    
    return clean_result.image_bytes

@router.post("/image")
async def process_full_pipeline_single(
    file: UploadFile = File(...),
    downscale_width: int = Form(64),
    downscale_height: int = Form(64),
    num_colors: int = Form(16),
    target_size: int = Form(64),
    dither_method: DitherMethod = Form(DitherMethod.ORDERED),
    dither_strength: float = Form(0.5),
    alpha_threshold: int = Form(128),
    min_component_size: int = Form(2),
    add_outline: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    s3_client = Depends(get_s3_client),
    rembg_session = Depends(get_rembg_session),
):
    """
    Execute full pipeline for a single image, returning the image directly.
    """
    final_bytes = await process_single_pipeline(
        file=file,
        downscale_width=downscale_width,
        downscale_height=downscale_height,
        num_colors=num_colors,
        target_size=target_size,
        dither_method=dither_method,
        dither_strength=dither_strength,
        alpha_threshold=alpha_threshold,
        min_component_size=min_component_size,
        add_outline=add_outline,
        db=db,
        s3_client=s3_client,
        rembg_session=rembg_session
    )
    return Response(content=final_bytes, media_type="image/png")

@router.post("/images")
async def process_full_pipeline_multiple(
    files: List[UploadFile] = File(...),
    downscale_width: int = Form(64),
    downscale_height: int = Form(64),
    num_colors: int = Form(16),
    target_size: int = Form(64),
    dither_method: DitherMethod = Form(DitherMethod.ORDERED),
    dither_strength: float = Form(0.5),
    alpha_threshold: int = Form(128),
    min_component_size: int = Form(2),
    add_outline: bool = Form(True),
    db: AsyncSession = Depends(get_db),
    s3_client = Depends(get_s3_client),
    rembg_session = Depends(get_rembg_session),
):
    """
    Execute full pipeline for multiple images, returning them in a ZIP file.
    """
    tasks = []
    for file in files:
        task = process_single_pipeline(
            file=file,
            downscale_width=downscale_width,
            downscale_height=downscale_height,
            num_colors=num_colors,
            target_size=target_size,
            dither_method=dither_method,
            dither_strength=dither_strength,
            alpha_threshold=alpha_threshold,
            min_component_size=min_component_size,
            add_outline=add_outline,
            db=db,
            s3_client=s3_client,
            rembg_session=rembg_session
        )
        tasks.append(task)
        
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for idx, (file, result) in enumerate(zip_items := zip(files, results)):
            if isinstance(result, Exception):
                # Ignore failed files or add placeholder txt
                zip_file.writestr(f"error_{idx}.txt", str(result))
            else:
                original_filename = file.filename or f"image_{idx}.png"
                clean_filename = build_cleanup_filename(
                    original_filename, alpha_threshold, min_component_size, add_outline
                )
                zip_file.writestr(clean_filename, result)
                
    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer, 
        media_type="application/zip", 
        headers={"Content-Disposition": "attachment; filename=pipeline_results.zip"}
    )
