from uuid import UUID

from pydantic import BaseModel, Field


class DownscaledFileResponse(BaseModel):
    id: UUID = Field(..., description="Stored downscaled file id")
    filename: str = Field(..., description="Saved file name")
    url: str = Field(..., description="File access path (S3 URL)")
    source_file_id: UUID = Field(..., description="Source file id from original_files or nobg_files")
    source_type: str = Field(..., description="Resolved source table: original or nobg")
    target_width: int = Field(..., description="Requested output width")
    target_height: int = Field(..., description="Requested output height")
    status: str = Field(default="stored")


class MultipleDownscaledFileResponse(BaseModel):
    files: list[DownscaledFileResponse]
    failed: list[str]
    status: str = Field(default="stored")


class DownscaleByIdRequest(BaseModel):
    file_id: UUID = Field(..., description="File id from original_files or nobg_files")
    target_width: int = Field(..., gt=0, le=4096)
    target_height: int = Field(..., gt=0, le=4096)


class DownscaleByIdsRequest(BaseModel):
    file_ids: list[UUID] = Field(..., min_length=1, description="File ids from original_files or nobg_files")
    target_width: int = Field(..., gt=0, le=4096)
    target_height: int = Field(..., gt=0, le=4096)