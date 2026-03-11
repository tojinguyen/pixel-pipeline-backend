import os

from rembg import remove

from app.infrastructure.imaging.rembg_client import get_rembg_session


def remove_background(input_bytes: bytes) -> bytes:
    session = get_rembg_session()
    return remove(input_bytes, session=session)


def build_nobg_filename(original_filename: str | None) -> str:
    filename_base = os.path.splitext(original_filename or "")[0]
    if filename_base == "":
        filename_base = "image"
    return f"{filename_base}_nobg.png"
