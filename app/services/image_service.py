import asyncio
import numpy as np
from PIL import Image
import io
import os
import re
import uuid
import cv2

async def remove_background_async(input_bytes: bytes, session) -> bytes:
    def _remove_and_clean(data: bytes, sess) -> bytes:
        from rembg import remove

        img = Image.open(io.BytesIO(data)).convert("RGBA")
        
        # Limit max size to 512px
        max_size = 512 
        if max(img.width, img.height) > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        
        resized_bytes_io = io.BytesIO()
        img.save(resized_bytes_io, format="PNG")
        resized_data = resized_bytes_io.getvalue()

        removed_bytes = remove(resized_data, session=sess)
        img_nobg = Image.open(io.BytesIO(removed_bytes)).convert("RGBA")
        arr = np.array(img_nobg, dtype=np.uint8)

        alpha = arr[:, :, 3]
        alpha[alpha < 128] = 0
        alpha[alpha >= 128] = 255
        arr[:, :, 3] = alpha

        cross_kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
        opaque_mask = (alpha == 255)
        transparent_mask = (alpha == 0)

        dilated_transparent = cv2.dilate(
            transparent_mask.astype(np.uint8) * 255, cross_kernel, iterations=1
        )
        fringe_mask = opaque_mask & (dilated_transparent == 255)
        interior_mask = opaque_mask & ~fringe_mask

        if fringe_mask.any():
            for channel in range(3):
                interior_channel = np.where(interior_mask, arr[:, :, channel], 0)
                dilated_channel = cv2.dilate(
                    interior_channel.astype(np.uint8), cross_kernel, iterations=1
                )
                arr[:, :, channel] = np.where(fringe_mask, dilated_channel, arr[:, :, channel])

        result = Image.fromarray(arr, "RGBA")
        output_buffer = io.BytesIO()
        result.save(output_buffer, format="PNG")
        return output_buffer.getvalue()

    return await asyncio.to_thread(_remove_and_clean, input_bytes, session)

def build_nobg_filename(original_filename: str | None) -> str:
    filename_base = os.path.splitext(os.path.basename(original_filename or ""))[0]
    if not filename_base:
        filename_base = "image"
    return f"{filename_base}_nobg.png"


def build_storage_key(original_filename: str | None, folder: str) -> str:
    filename = os.path.basename(original_filename or "image.png")
    filename_base, extension = os.path.splitext(filename)
    safe_base = re.sub(r"[^A-Za-z0-9._-]+", "_", filename_base).strip("._") or "image"
    safe_extension = extension.lower() or ".png"
    return f"{folder}/{uuid.uuid4()}_{safe_base}{safe_extension}"
