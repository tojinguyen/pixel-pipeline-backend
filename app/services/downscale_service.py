import asyncio
import io
import os
from dataclasses import dataclass

from PIL import Image

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
) -> DownscaleResult:
    return await asyncio.to_thread(
        _downscale_image,
        input_bytes,
        target_width,
        target_height,
    )

def build_downscaled_filename(original_filename: str | None, target_width: int, target_height: int) -> str:
    filename_base = os.path.splitext(os.path.basename(original_filename or ""))[0]
    if not filename_base:
        filename_base = "image"
    return f"{filename_base}_{target_width}x{target_height}.png"

def _downscale_image(
    input_bytes: bytes,
    target_width: int,
    target_height: int,
) -> DownscaleResult:
    try:
        with Image.open(io.BytesIO(input_bytes)) as source_image:
            source_rgba = source_image.convert("RGBA")
            
            orig_width, orig_height = source_rgba.size
            
            scale_factor = min(target_width / orig_width, target_height / orig_height)
            
            new_width = max(1, int(orig_width * scale_factor))
            new_height = max(1, int(orig_height * scale_factor))
            
            resized_image = source_rgba.resize((new_width, new_height), Image.Resampling.NEAREST)
            
            centered_image = Image.new("RGBA", (target_width, target_height), (0, 0, 0, 0))
            
            left = (target_width - new_width) // 2
            top = (target_height - new_height) // 2
            
            centered_image.paste(resized_image, (left, top))

        output_buffer = io.BytesIO()
        centered_image.save(output_buffer, format="PNG")
        return DownscaleResult(
            image_bytes=output_buffer.getvalue(),
            output_width=target_width,
            output_height=target_height,
        )
    except Exception as exc:
        raise ImageProcessingError("Image downscaling failed") from exc

