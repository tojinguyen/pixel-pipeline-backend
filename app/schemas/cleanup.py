from uuid import UUID

from pydantic import BaseModel, Field


class CleanupFileResponse(BaseModel):
    id: UUID = Field(..., description="Stored cleanup file id")
    filename: str = Field(..., description="Saved file name")
    url: str = Field(..., description="File access path (S3 URL)")
    source_file_id: UUID = Field(..., description="Source pixelized file id")
    source_type: str = Field(..., description="Resolved source table: pixelized")
    min_component_size: int = Field(..., description="Minimum component size to keep")
    alpha_threshold: int = Field(..., description="Alpha threshold used to generate binary mask")
    add_outline: bool = Field(..., description="Whether to add a 1-pixel outline")
    status: str = Field(default="stored")


class MultipleCleanupFileResponse(BaseModel):
    files: list[CleanupFileResponse]
    failed: list[str]
    status: str = Field(default="stored")


class CleanupRequest(BaseModel):
    file_id: UUID = Field(..., description="Pixelized file id")
    min_component_size: int = Field(default=2, ge=1, le=20, description="Minimum component size to keep")
    alpha_threshold: int = Field(default=128, ge=0, le=255, description="Mask threshold from alpha channel")
    add_outline: bool = Field(default=True, description="Whether to add a 1-pixel outline")


class CleanupBatchRequest(BaseModel):
    file_ids: list[UUID] = Field(..., min_length=1, description="Pixelized file ids")
    kernel_size: int = Field(default=2, ge=1, le=15, description="Morphology kernel size")
    alpha_threshold: int = Field(default=128, ge=0, le=255, description="Mask threshold from alpha channel")
    iterations: int = Field(default=1, ge=1, le=10, description="Number of morphology iterations")