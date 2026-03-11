from fastapi import FastAPI

from app.api.router import api_router
from app.core.handlers import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.infrastructure.imaging.rembg_client import init_rembg_session
from app.infrastructure.storage.s3_client import init_s3_client


configure_logging()
logger = get_logger(__name__)

app = FastAPI(
    title="Pixel Forge API",
    version="0.1.0",
)


@app.on_event("startup")
def startup() -> None:
    init_s3_client()
    init_rembg_session()
    logger.info("Application dependencies initialized")


app.include_router(api_router)
register_exception_handlers(app)