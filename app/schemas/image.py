from uuid import UUID

from pydantic import BaseModel, Field


class ImageUploadResponse(BaseModel):
    id: UUID = Field(..., description="Stored file id")
    filename: str = Field(..., description="Saved file name")
    url: str = Field(..., description="File access path (S3 URL)")
    status: str = Field(default="stored")


class MultipleImageUploadResponse(BaseModel):
    files: list[ImageUploadResponse]
    failed: list[str]
    status: str = Field(default="stored")


class NoBgImageResponse(BaseModel):
    id: UUID = Field(..., description="Stored no-background file id")
    filename: str = Field(..., description="Saved file name")
    url: str = Field(..., description="File access path (S3 URL)")
    original_file_id: UUID | None = Field(default=None, description="Original file id if linked")
    status: str = Field(default="stored")


class MultipleNoBgImageResponse(BaseModel):
    files: list[NoBgImageResponse]
    failed: list[str]
    status: str = Field(default="stored")


class HealthResponse(BaseModel):
    status: str
