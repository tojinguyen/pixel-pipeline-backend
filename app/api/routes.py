from fastapi import APIRouter, File, UploadFile
from fastapi.responses import StreamingResponse
import io
import zipfile
from typing import List

from app.core.exceptions import StorageError
from app.services.image_service import build_nobg_filename, remove_background
from app.services.storage_service import get_file_url, upload_file

router = APIRouter()


async def _upload_file(file: UploadFile) -> dict | None:
    file_bytes = await file.read()
    filename = file.filename
    try:
        uploaded_key = upload_file(file_bytes, filename, file.content_type or "image/png")
    except StorageError:
        uploaded_key = ""

    if not uploaded_key:
        return None
    return {"filename": filename, "url": get_file_url(filename)}


async def _remove_background_file(file: UploadFile) -> bytes:
    input_bytes = await file.read()
    return remove_background(input_bytes)

@router.get("/")
def health():
    return {"status": "ok"}

@router.post("/upload/image")
async def upload_image(file: UploadFile = File(...)):
    """Upload a single image and store it in S3/MinIO."""
    saved_file = await _upload_file(file)
    if saved_file:
        return {"filename": saved_file["filename"], "url": saved_file["url"], "status": "stored"}
    return {"status": "error", "message": "Failed to upload to S3"}

@router.post("/upload/images")
async def upload_multiple_images(files: List[UploadFile] = File(...)):
    """Upload multiple images and store them in S3/MinIO."""
    saved_files = []
    for file in files:
        saved_file = await _upload_file(file)
        if saved_file:
            saved_files.append(saved_file)

    return {"files": saved_files, "status": "stored"}

@router.post("/remove-bg/image")
async def remove_bg_single_image(file: UploadFile = File(...)):
    """Remove background from a single uploaded image."""
    output_bytes = await _remove_background_file(file)
    return StreamingResponse(io.BytesIO(output_bytes), media_type="image/png")

@router.post("/remove-bg/images")
async def remove_bg_multiple_images(files: List[UploadFile] = File(...)):
    """Remove background from multiple uploaded images and return them as a ZIP file."""
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file in files:
            output_bytes = await _remove_background_file(file)

            new_filename = build_nobg_filename(file.filename)

            zip_file.writestr(new_filename, output_bytes)

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=images_nobg.zip"},
    )

@router.post("/pixelize")
async def pixelize(file: UploadFile = File(...)):
    return {"filename": file.filename}