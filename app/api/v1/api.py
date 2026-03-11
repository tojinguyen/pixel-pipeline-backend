from fastapi import APIRouter

from app.api.v1.endpoints.pipeline import router as pipeline_router


api_v1_router = APIRouter()
api_v1_router.include_router(pipeline_router, tags=["pipeline"])
