import io
import zipfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_rembg_session, get_s3_client
from app.core.exceptions import StorageError
from app.schemas.image import HealthResponse, ImageUploadResponse, MultipleImageUploadResponse
from app.services.image_service import build_nobg_filename, remove_background_async
from app.services.storage_service import get_file_url, upload_file_async


router = APIRouter()


def _safe_filename(filename: str | None, fallback: str = "image.png") -> str:
    return filename or fallback


@router.get("/", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.post("/upload/image", response_model=ImageUploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    s3_client=Depends(get_s3_client),
) -> ImageUploadResponse:
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file provided")

    filename = _safe_filename(file.filename)
    content_type = file.content_type or "image/png"

    try:
        await upload_file_async(file_bytes, filename, content_type, s3_client)
        return ImageUploadResponse(
            filename=filename,
            url=get_file_url(filename),
            status="stored",
        )
    except StorageError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/upload/images", response_model=MultipleImageUploadResponse)
async def upload_multiple_images(
    files: list[UploadFile] = File(...),
    s3_client=Depends(get_s3_client),
) -> MultipleImageUploadResponse:
    saved_files: list[ImageUploadResponse] = []
    failed_files: list[str] = []

    for file in files:
        file_bytes = await file.read()
        filename = _safe_filename(file.filename)

        if not file_bytes:
            failed_files.append(filename)
            continue

        try:
            await upload_file_async(file_bytes, filename, file.content_type or "image/png", s3_client)
            saved_files.append(
                ImageUploadResponse(
                    filename=filename,
                    url=get_file_url(filename),
                    status="stored",
                )
            )
        except StorageError:
            failed_files.append(filename)

    return MultipleImageUploadResponse(
        files=saved_files,
        failed=failed_files,
        status="completed" if not failed_files else "partial_success",
    )


@router.post("/remove-bg/image")
async def remove_bg_single_image(
    file: UploadFile = File(...),
    rembg_session=Depends(get_rembg_session),
) -> StreamingResponse:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    input_bytes = await file.read()

    try:
        output_bytes = await remove_background_async(input_bytes, rembg_session)
    except Exception:
        raise HTTPException(status_code=500, detail="Image processing failed")

    output_filename = build_nobg_filename(file.filename)
    return StreamingResponse(
        io.BytesIO(output_bytes),
        media_type="image/png",
        headers={"Content-Disposition": f'inline; filename="{output_filename}"'},
    )


@router.post("/remove-bg/images")
async def remove_bg_multiple_images(
    files: list[UploadFile] = File(...),
    rembg_session=Depends(get_rembg_session),
) -> StreamingResponse:
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file in files:
            input_bytes = await file.read()
            if not input_bytes:
                continue

            try:
                output_bytes = await remove_background_async(input_bytes, rembg_session)
                new_filename = build_nobg_filename(file.filename)
                zip_file.writestr(new_filename, output_bytes)
            except Exception:
                # Log error but continue processing remaining files
                continue

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="images_nobg.zip"'},
    )


@router.post("/pixelize")
async def pixelize(file: UploadFile = File(...)) -> dict[str, str]:
    return {"filename": _safe_filename(file.filename), "status": "todo"}
