# File: app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.handlers import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.infrastructure.database.engine import close_engine
from app.infrastructure.storage.s3_client import init_s3_client
from app.infrastructure.imaging.rembg_client import init_rembg_session  # <--- THÊM IMPORT NÀY
from app.models import image as image_models  # noqa: F401

configure_logging()
logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize heavy dependencies on startup and store them in app.state."""
    logger.info("Initializing application dependencies...")
    
    # 1. Khởi tạo S3 Client
    app.state.s3_client = init_s3_client()
    
    # 2. Pre-load Model AI ngay lúc start app thay vì đợi API call
    logger.info("Loading AI model (BiRefNet) into memory. This may take a few seconds...")
    app.state.rembg_session = init_rembg_session("birefnet-general")
    
    logger.info("Dependencies initialized successfully. Server is ready!")

    yield  # Application runs here

    logger.info("Shutting down application...")
    await close_engine()

app = FastAPI(
    title="Pixel Forge API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
register_exception_handlers(app)