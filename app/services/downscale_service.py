import asyncio
import io
import os
from dataclasses import dataclass

from PIL import Image

from app.core.downscale import ScaleAxis, ScaleByMode, resolve_scale_axis
from app.core.exceptions import ImageProcessingError


@dataclass(frozen=True)
class DownscaleResult:
    image_bytes: bytes
    output_width: int
    output_height: int


async def downscale_image_async(
    input_bytes: bytes,
    target_width: int,
    target_height: int,
    keep_aspect_ratio: bool = False,
    scale_by: ScaleByMode | str | None = None,
) -> DownscaleResult:
    return await asyncio.to_thread(
        _downscale_image,
        input_bytes,
        target_width,
        target_height,
        keep_aspect_ratio,
        scale_by,
    )


def build_downscaled_filename(original_filename: str | None, target_width: int, target_height: int) -> str:
    filename_base = os.path.splitext(os.path.basename(original_filename or ""))[0]
    if not filename_base:
        filename_base = "image"
    return f"{filename_base}_{target_width}x{target_height}.png"


def normalize_scale_by(scale_by: ScaleByMode | str | None) -> str | None:
    if scale_by is None:
        return None

    try:
        return resolve_scale_axis(scale_by).value
    except ValueError as exc:
        raise ImageProcessingError(
            "scale_by must be one of: width, height, horizontal, vertical, landscape, portrait"
        ) from exc


def _downscale_image(
    input_bytes: bytes,
    target_width: int,
    target_height: int,
    keep_aspect_ratio: bool,
    scale_by: ScaleByMode | str | None,
) -> DownscaleResult:
    try:
        with Image.open(io.BytesIO(input_bytes)) as source_image:
            source_rgba = source_image.convert("RGBA")
            output_width, output_height = _resolve_target_size(
                original_width=source_rgba.width,
                original_height=source_rgba.height,
                target_width=target_width,
                target_height=target_height,
                keep_aspect_ratio=keep_aspect_ratio,
                scale_by=scale_by,
            )
            resized_image = source_rgba.resize(
                (output_width, output_height),
                resample=Image.Resampling.NEAREST,
            )

        output_buffer = io.BytesIO()
        resized_image.save(output_buffer, format="PNG")
        return DownscaleResult(
            image_bytes=output_buffer.getvalue(),
            output_width=output_width,
            output_height=output_height,
        )
    except ValueError as exc:
        raise ImageProcessingError(
            "scale_by must be one of: width, height, horizontal, vertical, landscape, portrait"
        ) from exc
    except Exception as exc:
        raise ImageProcessingError("Image downscale failed") from exc


def _resolve_target_size(
    original_width: int,
    original_height: int,
    target_width: int,
    target_height: int,
    keep_aspect_ratio: bool,
    scale_by: ScaleByMode | str | None,
) -> tuple[int, int]:
    if not keep_aspect_ratio:
        return target_width, target_height

    scale_axis = resolve_scale_axis(scale_by)
    if scale_axis == ScaleAxis.WIDTH:
        scaled_height = max(1, round(original_height * (target_width / original_width)))
        return target_width, scaled_height

    scaled_width = max(1, round(original_width * (target_height / original_height)))
    return scaled_width, target_height
