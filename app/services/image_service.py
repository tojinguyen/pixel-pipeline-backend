import asyncio
import os
import re
import uuid


async def remove_background_async(input_bytes: bytes, session) -> bytes:
    """
    Run the rembg AI background removal in a thread pool to avoid
    blocking FastAPI's async event loop (CPU-bound work).
    """
    from rembg import remove

    return await asyncio.to_thread(remove, input_bytes, session=session)


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
