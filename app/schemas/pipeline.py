from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field

from app.services.pixelize_service import DitherMethod


class PipelineParams(BaseModel):
    """Shared pipeline configuration across single and batch endpoints."""

    target_pixel_size: int = Field(
        default=64,
        ge=8,
        le=512,
        description="Pixel-art grid size in pixels (8–512). 64 is the RPG sprite standard.",
    )
    num_colors: int = Field(
        default=16,
        ge=1,
        le=256,
        description="Palette size (1–256). 16 = SNES/GBA aesthetic.",
    )
    dither_method: DitherMethod = Field(
        default=DitherMethod.ORDERED,
        description="Dithering algorithm: ordered (Bayer 8×8), floyd-steinberg, atkinson, or none.",
    )
    dither_strength: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="Dithering intensity (0.0 = off, 1.0 = maximum). 0.4 balances texture and clarity.",
    )
    alpha_threshold: int = Field(
        default=128,
        ge=0,
        le=255,
        description="Alpha binarization cutoff. Pixels below this become fully transparent.",
    )
    min_component_size: int = Field(
        default=2,
        ge=1,
        le=20,
        description="Connected components ≤ this area (px²) are removed as noise.",
    )
    add_outline: bool = Field(
        default=True,
        description="Add a 1-pixel black outline around the sprite silhouette.",
    )


class PipelineFileResponse(BaseModel):
    id: UUID = Field(..., description="Pipeline file record ID")
    original_filename: str = Field(..., description="Original uploaded filename")
    filename: str = Field(..., description="Processed output filename")
    url: str = Field(..., description="S3 URL of the processed image")
    file_size: int = Field(..., description="File size in bytes")
    target_pixel_size: int
    num_colors: int
    dither_method: str
    dither_strength: float
    alpha_threshold: int
    min_component_size: int
    add_outline: bool
    created_at: datetime
    status: str = Field(default="stored")

    class Config:
        from_attributes = True


class MultiplePipelineResponse(BaseModel):
    files: list[PipelineFileResponse]
    failed: list[str] = Field(default_factory=list)
    status: str = Field(default="completed")
