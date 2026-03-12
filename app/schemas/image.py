from pydantic import BaseModel, Field


class ImageUploadResponse(BaseModel):
    filename: str = Field(..., description="Saved file name")
    url: str = Field(..., description="File access path (S3 URL)")
    status: str = Field(default="stored")


class MultipleImageUploadResponse(BaseModel):
    files: list[ImageUploadResponse]
    failed: list[str]
    status: str = Field(default="stored")


class HealthResponse(BaseModel):
    status: str
