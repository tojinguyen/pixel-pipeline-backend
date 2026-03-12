# 📋 Comprehensive FastAPI Backend Refactoring Guide

**Objective:** Transform the codebase from a "working" mentality to a production-ready FastAPI standard (Async, Type-safe, Pydantic, Dependency Injection).

---

## 1. New Directory Structure (FastAPI Standard)

Eliminate confusion about naming conventions. Adopt the Python ecosystem standard:
- `models/`: Reserved for Database Models (currently not applicable).
- `schemas/`: Reserved for Data Transfer Objects (DTOs) using Pydantic.

```
app/
├── api/
│   ├── dependencies.py      <-- NEW: Contains Dependency Injection
│   ├── router.py
│   └── v1/
│       └── endpoints/
│           └── pipeline.py  <-- Complete refactor
├── core/
│   ├── config.py
│   ├── exceptions.py
│   ├── handlers.py
│   └── logging.py
├── schemas/                 <-- NEW: Contains Pydantic DTOs
│   └── image.py
├── services/
│   ├── image_service.py     <-- Refactor to Async (Non-blocking)
│   └── storage_service.py   <-- Refactor to Async (Non-blocking)
└── main.py                  <-- Refactor to use Lifespan
```

---

## 2. Detailed File Modifications

### Step 1: Initialize Pydantic Schemas (DTOs)

**Create new file:** `app/schemas/image.py`

Never return raw dicts in FastAPI. Let Pydantic handle validation and Swagger documentation generation.

```python
from pydantic import BaseModel, Field

class ImageUploadResponse(BaseModel):
    filename: str = Field(..., description="Saved file name")
    url: str = Field(..., description="File access path (S3 URL)")
    status: str = Field(default="stored")

class MultipleImageUploadResponse(BaseModel):
    files: list[ImageUploadResponse]
    failed: list[str]
    status: str = Field(default="stored")

class HealthResponse(BaseModel):
    status: str
```

---

### Step 2: Set Up Lifespan & Remove Global Variables

**Modify file:** `app/main.py`

Remove deprecated `@app.on_event("startup")` and eliminate global variable imports.

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.api.router import api_router
from app.core.handlers import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.infrastructure.imaging.rembg_client import init_rembg_session
from app.infrastructure.storage.s3_client import init_s3_client

configure_logging()
logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize heavy connections when server starts and store in app.state
    logger.info("Initializing application dependencies...")
    app.state.s3_client = init_s3_client()
    app.state.rembg_session = init_rembg_session("u2net")
    logger.info("Dependencies initialized successfully.")
    
    yield  # Application runs here
    
    # Cleanup logic when server shuts down (if needed)
    logger.info("Shutting down application...")

app = FastAPI(
    title="Pixel Forge API",
    version="0.1.0",
    lifespan=lifespan,  # Use lifespan instead of on_event
)

app.include_router(api_router)
register_exception_handlers(app)
```

**Note:** Refactor `init_s3_client()` and `init_rembg_session()` in the infrastructure folder to return objects instead of assigning to global variables.

---

### Step 3: Create Dependency Injection (DI)

**Create new file:** `app/api/dependencies.py`

FastAPI uses DI to safely access connections from app.state and facilitate testing (mocking).

```python
from fastapi import Request
from botocore.client import BaseClient

def get_s3_client(request: Request) -> BaseClient:
    return request.app.state.s3_client

def get_rembg_session(request: Request):
    return request.app.state.rembg_session
```

---

### Step 4: Rescue Event Loop from Blocking Code (Critical)

**Modify files:** `app/services/image_service.py` and `app/services/storage_service.py`

Since rembg (CPU-bound) and boto3 (network I/O) are synchronous code, wrapping them in an async function will block the entire server. Use `asyncio.to_thread()` to offload them.

#### `app/services/image_service.py`

```python
import os
import asyncio
from rembg import remove

async def remove_background_async(input_bytes: bytes, session) -> bytes:
    """
    Run heavy AI tasks (rembg) in a Threadpool to avoid blocking 
    FastAPI's Event Loop.
    """
    return await asyncio.to_thread(remove, input_bytes, session=session)

def build_nobg_filename(original_filename: str | None) -> str:
    filename_base = os.path.splitext(original_filename or "")[0]
    if not filename_base:
        filename_base = "image"
    return f"{filename_base}_nobg.png"
```

#### `app/services/storage_service.py`

```python
import asyncio
from botocore.exceptions import NoCredentialsError
from app.core.config import get_settings
from app.core.exceptions import StorageError

async def upload_file_async(file_bytes: bytes, filename: str, content_type: str, client) -> str:
    """
    Offload S3 upload task (boto3 blocking) to Threadpool.
    """
    settings = get_settings()
    try:
        await asyncio.to_thread(
            client.put_object,
            Bucket=settings.s3_bucket_name,
            Key=filename,
            Body=file_bytes,
            ContentType=content_type,
        )
        return filename
    except NoCredentialsError as exc:
        raise StorageError("Credentials not available") from exc
    except Exception as exc:
        raise StorageError(f"Error uploading to S3: {exc}") from exc

def get_file_url(filename: str) -> str:
    settings = get_settings()
    if settings.s3_endpoint_url:
        return f"{settings.s3_endpoint_url}/{settings.s3_bucket_name}/{filename}"
    return f"https://{settings.s3_bucket_name}.s3.{settings.aws_region}.amazonaws.com/{filename}"
```

---

### Step 5: Rewrite Router - Proper RESTful Error Handling

**Modify file:** `app/api/v1/endpoints/pipeline.py`

Use Schemas (DTOs), HTTP Exceptions (500/400), and Dependency Injection instead of dicts and hidden exceptions.

```python
import io
import zipfile
from fastapi import APIRouter, File, UploadFile, Depends, HTTPException
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
def health():
    return HealthResponse(status="ok")

@router.post("/upload/image", response_model=ImageUploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    s3_client = Depends(get_s3_client)  # Inject S3 Client
):
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
            status="stored"
        )
    except StorageError as e:
        # Server errors must return 500, not 200 OK
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload/images", response_model=MultipleImageUploadResponse)
async def upload_multiple_images(
    files: list[UploadFile] = File(...),
    s3_client = Depends(get_s3_client)
):
    saved_files = []
    failed_files = []

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
                    status="stored"
                )
            )
        except StorageError:
            failed_files.append(filename)

    return MultipleImageUploadResponse(
        files=saved_files,
        failed=failed_files,
        status="completed" if not failed_files else "partial_success"
    )

@router.post("/remove-bg/image")
async def remove_bg_single_image(
    file: UploadFile = File(...),
    rembg_session = Depends(get_rembg_session)  # Inject Rembg Session
) -> StreamingResponse:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    input_bytes = await file.read()
    
    try:
        output_bytes = await remove_background_async(input_bytes, rembg_session)
    except Exception as e:
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
    rembg_session = Depends(get_rembg_session)
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
                # Log error but continue with other files
                continue

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="images_nobg.zip"'},
    )
```

---

## 3. Key Principles for Production-Ready Code

### ✅ **Use Async for I/O Operations**
- Database queries
- HTTP requests
- File I/O
- S3 operations

### ✅ **Offload CPU-Bound Work**
```python
# Instead of blocking the event loop
result = heavy_computation(data)  # ❌ BLOCKS

# Use asyncio.to_thread
result = await asyncio.to_thread(heavy_computation, data)  # ✅ NON-BLOCKING
```

### ✅ **Always Validate with Pydantic**
```python
# Return response models, not dicts
return HealthResponse(status="ok")  # ✅ Type-safe
return {"status": "ok"}  # ❌ No validation
```

### ✅ **Use Dependency Injection for Testability**
```python
# Inject dependencies
async def endpoint(client = Depends(get_s3_client)):  # ✅ Easy to mock
    pass

# Instead of global variables
s3_client = S3Client()  # ❌ Hard to test
```

### ✅ **Proper Error Handling**
```python
# Use HTTPException with correct status codes
raise HTTPException(status_code=500, detail="Server error")  # ✅ Proper HTTP

# Instead of generic exceptions
raise Exception("Something failed")  # ❌ No HTTP context
```

---

## 4. Installation & Setup

### Using **pip** (Python 3.13)
```bash
python3.13 -m pip install --upgrade pip
python3.13 -m pip install fastapi uvicorn pydantic boto3 rembg python-multipart
python3.13 -m pip install -r requirements.txt
```

### Using **uv** (Faster alternative - Python 3.13)
```bash
uv pip install fastapi uvicorn pydantic boto3 rembg python-multipart
uv sync
```

### `requirements.txt`
```
fastapi==0.109.0
uvicorn[standard]==0.27.0
pydantic==2.5.3
pydantic-settings==2.1.0
boto3==1.34.0
rembg==0.0.50
python-multipart==0.0.6
```

### Run the Application
```bash
# Using uvicorn directly
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Or using Python module
python -m uvicorn app.main:app --reload
```

---

## 5. Testing Async Endpoints

Example test with Python's `pytest` and `httpx`:

```bash
pip install pytest pytest-asyncio httpx
```

```python
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_upload_image(mocker):
    # Mock S3 client
    mock_s3 = mocker.patch("app.api.dependencies.get_s3_client")
    
    with open("test_image.png", "rb") as f:
        response = client.post(
            "/upload/image",
            files={"file": f}
        )
    
    assert response.status_code == 200
    assert "url" in response.json()
```

---

## 6. Key Improvements Summary

| Aspect | Before | After |
|--------|--------|-------|
| **Structure** | Chaotic | Organized (schemas/, services/) |
| **Type Safety** | Raw dicts | Pydantic models |
| **Concurrency** | Blocking event loop | Non-blocking with asyncio |
| **Dependency Management** | Global variables | Dependency Injection |
| **Error Handling** | Hidden exceptions | HTTP status codes |
| **Testing** | Difficult | Easy (mockable dependencies) |
| **Documentation** | Manual | Auto-generated Swagger |

---

## 7. Next Steps

1. **Implement logging** in `app/core/logging.py` using Python's `logging` module
2. **Add database support** with SQLAlchemy ORM (if needed)
3. **Create unit tests** for each service layer
4. **Set up CI/CD** with GitHub Actions or similar
5. **Add API documentation** with OpenAPI/Swagger (automatic with FastAPI)
6. **Implement request validation** middleware for additional security
7. **Add monitoring & observability** with tools like Prometheus

---

**This refactoring transforms your backend into a production-grade, maintainable, and testable application.**
