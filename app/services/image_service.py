import os
import asyncio


async def remove_background_async(input_bytes: bytes, session) -> bytes:
    """
    Run the rembg AI background removal in a thread pool to avoid
    blocking FastAPI's async event loop (CPU-bound work).
    """
    from rembg import remove

    return await asyncio.to_thread(remove, input_bytes, session=session)


def build_nobg_filename(original_filename: str | None) -> str:
    filename_base = os.path.splitext(original_filename or "")[0]
    if not filename_base:
        filename_base = "image"
    return f"{filename_base}_nobg.png"
