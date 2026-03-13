from uuid import UUID
from pydantic import BaseModel, Field

class PixelizedFileResponse(BaseModel):
    id: UUID = Field(..., description="Stored pixelized file id")
    filename: str = Field(..., description="Saved file name")
    url: str = Field(..., description="File access path (S3 URL)")
    source_file_id: UUID = Field(..., description="Source file id from original, nobg, or downscaled files")
    source_type: str = Field(..., description="Resolved source table: original, nobg, or downscaled")
    mode: str = Field(..., description="Pixelization mode used: 'auto' or 'preset'")
    num_colors: int | None = Field(None, description="Number of colors if auto mode was used")
    palette_name: str | None = Field(None, description="Name of the palette if preset mode was used")
    status: str = Field(default="stored")

class MultiplePixelizedFileResponse(BaseModel):
    files: list[PixelizedFileResponse]
    failed: list[str]
    status: str = Field(default="stored")

class PixelizeByIdRequest(BaseModel):
    file_id: UUID = Field(..., description="File id from original, nobg, or downscaled files")
    mode: str = Field(default="auto", description="Mode of pixelization: 'auto' limit colors, 'preset' uses predefined palette")
    num_colors: int | None = Field(default=None, description="Limit to N colors when mode is auto.")
    palette_name: str | None = Field(default=None, description="Name of the palette when mode is preset.")

class PixelizeByIdsRequest(BaseModel):
    file_ids: list[UUID] = Field(..., min_length=1, description="File ids from original, nobg, or downscaled files")
    mode: str = Field(default="auto", description="Mode of pixelization: 'auto' limit colors, 'preset' uses predefined palette")
    num_colors: int | None = Field(default=None, description="Limit to N colors when mode is auto.")
    palette_name: str | None = Field(default=None, description="Name of the palette when mode is preset.")
