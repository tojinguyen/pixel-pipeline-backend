from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.handlers import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.infrastructure.database.engine import close_engine
from app.infrastructure.storage.s3_client import init_s3_client
from app.models import image as image_models  # noqa: F401


configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize heavy dependencies on startup and store them in app.state."""
    logger.info("Initializing application dependencies...")
    app.state.s3_client = init_s3_client()
    app.state.rembg_session = None
    logger.info("Dependencies initialized successfully.")

    yield  # Application runs here

    logger.info("Shutting down application...")
    await close_engine()


app = FastAPI(
    title="Pixel Forge API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router)
register_exception_handlers(app)