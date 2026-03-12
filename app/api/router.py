from fastapi import APIRouter

from app.api.v1.api import api_v1_router


api_router = APIRouter()
api_router.include_router(api_v1_router, prefix="/api/v1")
