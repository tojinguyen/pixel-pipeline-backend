from __future__ import annotations

from rembg import new_session

from app.core.exceptions import ImageProcessingError


_rembg_session = None


def init_rembg_session(model_name: str = "u2net") -> None:
    global _rembg_session
    _rembg_session = new_session(model_name)


def get_rembg_session():
    if _rembg_session is None:
        raise ImageProcessingError("Background removal session is not initialized")
    return _rembg_session
