from fastapi import APIRouter

from app.api.v1.endpoints.cleanup import router as cleanup_router
from app.api.v1.endpoints.downscale import router as downscale_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.pixelize import router as pixelize_router
from app.api.v1.endpoints.remove_bg import router as remove_bg_router
from app.api.v1.endpoints.upload import router as upload_router


api_v1_router = APIRouter()
api_v1_router.include_router(health_router, tags=["health"])
api_v1_router.include_router(upload_router, tags=["upload"])
api_v1_router.include_router(remove_bg_router, tags=["remove_bg"])
api_v1_router.include_router(downscale_router, tags=["downscale"])
api_v1_router.include_router(pixelize_router, tags=["pixelize"])
api_v1_router.include_router(cleanup_router, tags=["cleanup"])
