from uuid import UUID
from pydantic import BaseModel, Field

from app.services.pixelize_service import DitherMethod

class PixelizedFileResponse(BaseModel):
    id: UUID = Field(..., description="Stored pixelized file id")
    filename: str = Field(..., description="Saved file name")
    url: str = Field(..., description="File access path (S3 URL)")
    source_file_id: UUID = Field(..., description="Source file id from downscaled_files")
    num_colors: int = Field(..., description="Number of colors used")
    status: str = Field(default="stored")

class MultiplePixelizedFileResponse(BaseModel):
    files: list[PixelizedFileResponse]
    failed: list[str]
    status: str = Field(default="stored")

class SinglePixelizeRequest(BaseModel):
    file_id: UUID = Field(..., description="File id from downscaled_files")
    num_colors: int = Field(default=16, description="Limit to N colors")
    target_size: int = Field(default=64, description="Pixel-art grid size")
    dither_method: DitherMethod = Field(default=DitherMethod.ORDERED, description="Dithering method")
    dither_strength: float = Field(default=0.5, description="Dithering intensity")

class MultiplePixelizeRequest(BaseModel):
    file_ids: list[UUID] = Field(..., min_length=1, description="File ids from downscaled_files")
    num_colors: int = Field(default=16, description="Limit to N colors")
    target_size: int = Field(default=64, description="Pixel-art grid size")
    dither_method: DitherMethod = Field(default=DitherMethod.ORDERED, description="Dithering method")
    dither_strength: float = Field(default=0.5, description="Dithering intensity")
