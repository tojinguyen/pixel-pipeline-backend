from fastapi import APIRouter

from app.api.v1.endpoints.downscale import router as downscale_router
from app.api.v1.endpoints.pipeline import router as pipeline_router


api_v1_router = APIRouter()
api_v1_router.include_router(pipeline_router, tags=["pipeline"])
api_v1_router.include_router(downscale_router, tags=["downscale"])
