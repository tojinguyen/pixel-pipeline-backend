import asyncio
import io
import os

from PIL import Image

from app.core.exceptions import ImageProcessingError


async def downscale_image_async(input_bytes: bytes, target_width: int, target_height: int) -> bytes:
    return await asyncio.to_thread(_downscale_image, input_bytes, target_width, target_height)


def build_downscaled_filename(original_filename: str | None, target_width: int, target_height: int) -> str:
    filename_base = os.path.splitext(os.path.basename(original_filename or ""))[0]
    if not filename_base:
        filename_base = "image"
    return f"{filename_base}_{target_width}x{target_height}.png"


def _downscale_image(input_bytes: bytes, target_width: int, target_height: int) -> bytes:
    try:
        with Image.open(io.BytesIO(input_bytes)) as source_image:
            resized_image = source_image.convert("RGBA").resize(
                (target_width, target_height),
                resample=Image.Resampling.NEAREST,
            )

        output_buffer = io.BytesIO()
        resized_image.save(output_buffer, format="PNG")
        return output_buffer.getvalue()
    except Exception as exc:
        raise ImageProcessingError("Image downscale failed") from exc