from fastapi import APIRouter

from app.api.v1.api import api_v1_router
from app.api.v1.endpoints.pipeline import router as legacy_router


api_router = APIRouter()
api_router.include_router(api_v1_router, prefix="/api/v1")
# Keep old paths temporarily for backward compatibility.
api_router.include_router(legacy_router, include_in_schema=False)
