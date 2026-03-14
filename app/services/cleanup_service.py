import asyncio
import io
import os
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from app.core.cleanup import CleanupError


@dataclass(frozen=True)
class CleanupResult:
    image_bytes: bytes
    kernel_size: int
    alpha_threshold: int
    iterations: int


async def cleanup_image_async(
    input_bytes: bytes,
    kernel_size: int = 2,
    alpha_threshold: int = 128,
    iterations: int = 1,
) -> CleanupResult:
    if kernel_size < 1 or kernel_size > 15:
        raise CleanupError("kernel_size must be between 1 and 15")
    if alpha_threshold < 0 or alpha_threshold > 255:
        raise CleanupError("alpha_threshold must be between 0 and 255")
    if iterations < 1 or iterations > 10:
        raise CleanupError("iterations must be between 1 and 10")

    return await asyncio.to_thread(
        _process_cleanup,
        input_bytes,
        kernel_size,
        alpha_threshold,
        iterations,
    )


def build_cleanup_filename(
    original_filename: str | None,
    kernel_size: int,
    alpha_threshold: int,
    iterations: int,
) -> str:
    filename_base = os.path.splitext(os.path.basename(original_filename or ""))[0]
    if not filename_base:
        filename_base = "image"
    return f"{filename_base}_cleanup_k{kernel_size}_a{alpha_threshold}_i{iterations}.png"


def _process_cleanup(
    input_bytes: bytes,
    kernel_size: int,
    alpha_threshold: int,
    iterations: int,
) -> CleanupResult:
    try:
        with Image.open(io.BytesIO(input_bytes)) as source_image:
            rgba_image = source_image.convert("RGBA")
            image_array = np.array(rgba_image)

        alpha_channel = image_array[:, :, 3]
        _, mask = cv2.threshold(alpha_channel, alpha_threshold, 255, cv2.THRESH_BINARY)
        kernel = np.ones((kernel_size, kernel_size), np.uint8)

        mask_closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=iterations)
        mask_cleaned = cv2.morphologyEx(mask_closed, cv2.MORPH_OPEN, kernel, iterations=iterations)

        newly_opaque = cv2.bitwise_and(mask_cleaned, cv2.bitwise_not(mask))
        
        r, g, b = image_array[:, :, 0], image_array[:, :, 1], image_array[:, :, 2]
        is_black_rgb = (r == 0) & (g == 0) & (b == 0)
        
        force_transparent = newly_opaque.astype(bool) & is_black_rgb
        mask_cleaned[force_transparent] = 0

        image_array[:, :, 3] = mask_cleaned

        output_buffer = io.BytesIO()
        Image.fromarray(image_array, "RGBA").save(output_buffer, format="PNG")

        return CleanupResult(
            image_bytes=output_buffer.getvalue(),
            kernel_size=kernel_size,
            alpha_threshold=alpha_threshold,
            iterations=iterations,
        )
    except Exception as exc:
        raise CleanupError(f"Image cleanup failed: {str(exc)}") from exc