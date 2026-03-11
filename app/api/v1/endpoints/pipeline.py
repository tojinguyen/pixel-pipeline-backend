import io
import zipfile
from typing import List

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import StreamingResponse

from app.core.exceptions import StorageError
from app.services.image_service import build_nobg_filename, remove_background
from app.services.storage_service import get_file_url, upload_file


router = APIRouter()


def _safe_filename(filename: str | None, fallback: str = "image.png") -> str:
    return filename or fallback


async def _upload_file(file: UploadFile) -> dict[str, str] | None:
    file_bytes = await file.read()
    filename = _safe_filename(file.filename)

    if not file_bytes:
        return None

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
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/upload/image")
async def upload_image(file: UploadFile = File(...)) -> dict[str, str]:
    saved_file = await _upload_file(file)
    if saved_file:
        return {
            "filename": saved_file["filename"],
            "url": saved_file["url"],
            "status": "stored",
        }
    return {"status": "error", "message": "Failed to upload to S3"}


@router.post("/upload/images")
async def upload_multiple_images(files: List[UploadFile] = File(...)) -> dict[str, object]:
    saved_files = []
    failed_files = []

    for file in files:
        saved_file = await _upload_file(file)
        if saved_file:
            saved_files.append(saved_file)
        else:
            failed_files.append(_safe_filename(file.filename))

    return {"files": saved_files, "failed": failed_files, "status": "stored"}


@router.post("/remove-bg/image")
async def remove_bg_single_image(file: UploadFile = File(...)) -> StreamingResponse:
    output_bytes = await _remove_background_file(file)
    output_filename = build_nobg_filename(file.filename)
    return StreamingResponse(
        io.BytesIO(output_bytes),
        media_type="image/png",
        headers={"Content-Disposition": f"inline; filename={output_filename}"},
    )


@router.post("/remove-bg/images")
async def remove_bg_multiple_images(files: List[UploadFile] = File(...)) -> StreamingResponse:
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
async def pixelize(file: UploadFile = File(...)) -> dict[str, str]:
    return {"filename": _safe_filename(file.filename), "status": "todo"}
