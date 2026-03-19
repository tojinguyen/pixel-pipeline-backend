# File: app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.handlers import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.infrastructure.database.engine import close_engine
from app.infrastructure.storage.s3_client import init_s3_client
from app.infrastructure.imaging.rembg_client import init_rembg_session
from app.models import image as image_models  # noqa: F401

configure_logging()
logger = get_logger(__name__)
settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize dependencies on startup and store them in app.state."""
    logger.info("Initializing application dependencies...")
    
    # 1. Khởi tạo S3 Client
    app.state.s3_client = init_s3_client()
    
    logger.info(
        "Loading background removal model '%s' into memory. This may take a few seconds...",
        settings.rembg_model_name,
    )
    app.state.rembg_session = init_rembg_session(settings.rembg_model_name)
    
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