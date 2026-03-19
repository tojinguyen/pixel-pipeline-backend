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
    target_width: int = Field(..., description="Downscaled target width")
    target_height: int = Field(..., description="Downscaled target height")
    status: str = Field(default="stored")


class MultipleNoBgImageResponse(BaseModel):
    files: list[NoBgImageResponse]
    failed: list[str]
    status: str = Field(default="stored")


class SingleRemoveBgRequest(BaseModel):
    original_file_id: UUID
    target_width: int = Field(..., gt=0, description="Target width for downscaling")
    target_height: int = Field(..., gt=0, description="Target height for downscaling")


class MultipleRemoveBgRequest(BaseModel):
    original_file_ids: list[UUID]
    target_width: int = Field(..., gt=0, description="Target width for downscaling")
    target_height: int = Field(..., gt=0, description="Target height for downscaling")


class HealthResponse(BaseModel):
    status: str
