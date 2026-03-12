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
    """Initialize heavy dependencies on startup and store them in app.state."""
    logger.info("Initializing application dependencies...")
    app.state.s3_client = init_s3_client()
    app.state.rembg_session = init_rembg_session("u2net")
    logger.info("Dependencies initialized successfully.")

    yield  # Application runs here

    logger.info("Shutting down application...")


app = FastAPI(
    title="Pixel Forge API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router)
register_exception_handlers(app)