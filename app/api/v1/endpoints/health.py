from fastapi import APIRouter

from app.schemas.image import HealthResponse

router = APIRouter()


@router.get("/", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")
