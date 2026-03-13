import asyncio
import io
import os
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from app.core.exceptions import ImageProcessingError

@dataclass(frozen=True)
class PixelizeResult:
    image_bytes: bytes
    num_colors: int

async def pixelize_image_async(
    input_bytes: bytes,
    num_colors: int = 16,
) -> PixelizeResult:
    if num_colors <= 0 or num_colors > 256:
        raise ImageProcessingError("num_colors must be between 1 and 256")

    return await asyncio.to_thread(
        _process_pixelize,
        input_bytes,
        num_colors,
    )

def build_pixelized_filename(original_filename: str | None, num_colors: int) -> str:
    filename_base = os.path.splitext(os.path.basename(original_filename or ""))[0]
    if not filename_base:
        filename_base = "image"
        
    return f"{filename_base}_{num_colors}colors.png"

def _process_pixelize(
    input_bytes: bytes,
    num_colors: int,
) -> PixelizeResult:
    try:
        with Image.open(io.BytesIO(input_bytes)) as source_image:
            image_rgba = source_image.convert("RGBA")
            
            img_array = np.array(image_rgba)
            alpha = img_array[:, :, 3]
            rgb = img_array[:, :, :3]

            # Reshape thành list pixels
            pixels = rgb.reshape(-1, 3).astype(np.float32)

            # K-Means clustering
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2)
            _, labels, centers = cv2.kmeans(
                pixels, num_colors, None, criteria, 10, cv2.KMEANS_RANDOM_CENTERS
            )

            # Map mỗi pixel về màu centroid gần nhất
            centers = np.uint8(centers)
            quantized_pixels = centers[labels.flatten()]
            quantized_rgb = quantized_pixels.reshape(rgb.shape)

            # Khôi phục channel alpha
            quantized_rgba = np.dstack([quantized_rgb, alpha])
            result_image = Image.fromarray(quantized_rgba, "RGBA")

            output_buffer = io.BytesIO()
            result_image.save(output_buffer, format="PNG")
            
            return PixelizeResult(
                image_bytes=output_buffer.getvalue(),
                num_colors=num_colors,
            )
    except Exception as exc:
        raise ImageProcessingError(f"Pixelization failed: {exc}") from exc
