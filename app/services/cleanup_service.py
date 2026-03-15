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
    alpha_threshold: int
    min_component_size: int
    add_outline: bool


async def cleanup_image_async(
    input_bytes: bytes,
    alpha_threshold: int = 128,
    min_component_size: int = 2,
    add_outline: bool = True,
) -> CleanupResult:
    if alpha_threshold < 0 or alpha_threshold > 255:
        raise CleanupError("alpha_threshold must be between 0 and 255")
    if min_component_size < 1 or min_component_size > 20:
        raise CleanupError("min_component_size must be between 1 and 20")

    return await asyncio.to_thread(
        _process_cleanup,
        input_bytes,
        alpha_threshold,
        min_component_size,
        add_outline,
    )


def build_cleanup_filename(
    original_filename: str | None,
    alpha_threshold: int,
    min_component_size: int,
    add_outline: bool,
) -> str:
    filename_base = os.path.splitext(os.path.basename(original_filename or ""))[0]
    if not filename_base:
        filename_base = "image"
    outline_tag = "outline" if add_outline else "no_outline"
    return f"{filename_base}_cleanup_a{alpha_threshold}_c{min_component_size}_{outline_tag}.png"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hard_alpha_binarize(alpha: np.ndarray, threshold: int) -> np.ndarray:
    """
    Enforce strict binary alpha — no semi-transparent edges allowed in pixel art.

    Every pixel is either fully opaque (255) or fully transparent (0).
    This is a hard prerequisite for all subsequent steps.
    """
    mask = np.zeros_like(alpha, dtype=np.uint8)
    mask[alpha >= threshold] = 255
    return mask


def _remove_orphan_pixels(
    mask: np.ndarray,
    min_component_size: int,
) -> np.ndarray:
    """
    Connected Component Labeling (CCL) orphan removal.

    Scans the entire alpha mask for isolated pixel "islands" whose total area
    is <= min_component_size. These are noise artifacts left over by the
    downscaling step. Each orphan is erased (set transparent) so the colour
    blocks remain clean.

    Why NOT morphology (MORPH_OPEN / MORPH_CLOSE)?
    Morphological operations use a uniform square kernel that rounds sharp
    corners and destroys thin diagonal lines — exactly the features that make
    pixel-art characters look hand-crafted. CCL only touches the actual
    outlier islands, leaving every valid shape untouched.
    """
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask, connectivity=8
    )

    cleaned = mask.copy()
    for label_id in range(1, num_labels):          # label 0 = background
        area = stats[label_id, cv2.CC_STAT_AREA]
        if area <= min_component_size:
            cleaned[labels == label_id] = 0

    return cleaned


def _add_outline(image_array: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """
    Automatic 1-pixel black outline via Alpha Dilation (cross kernel).

    Algorithm:
      1. Dilate the binary alpha mask by exactly 1 pixel using a cross-shaped
         (plus-sign) structuring element — this expands only in the four
         cardinal directions, preserving diagonal corners.
      2. XOR the dilated mask with the original to isolate the new border ring.
      3. Paint that ring pure black (0, 0, 0) at full opacity (255).

    Result: a crisp outline that:
      - Hides any remaining jagged edges at the character boundary.
      - Visually separates the sprite from any game background.
    """
    cross_kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    dilated = cv2.dilate(mask, cross_kernel, iterations=1)

    # Ring = pixels added by dilation that were not originally opaque
    outline_ring = cv2.bitwise_and(dilated, cv2.bitwise_not(mask))

    result = image_array.copy()
    ring_pixels = outline_ring > 0
    result[ring_pixels, 0] = 0    # R → black
    result[ring_pixels, 1] = 0    # G → black
    result[ring_pixels, 2] = 0    # B → black
    result[ring_pixels, 3] = 255  # A → fully opaque
    return result


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def _process_cleanup(
    input_bytes: bytes,
    alpha_threshold: int,
    min_component_size: int,
    add_outline: bool,
) -> CleanupResult:
    try:
        with Image.open(io.BytesIO(input_bytes)) as src:
            image_array = np.array(src.convert("RGBA"))

        # ── Step 1: Hard Alpha Binarization ──────────────────────────────────
        # Collapse all semi-transparent pixels to either 0 or 255.
        # Pixel art must have razor-sharp edges — no anti-aliasing.
        binary_mask = _hard_alpha_binarize(image_array[:, :, 3], alpha_threshold)

        # ── Step 2: CCL Orphan Removal ────────────────────────────────────────
        # Erase isolated pixel islands (noise) without touching valid shapes.
        clean_mask = _remove_orphan_pixels(binary_mask, min_component_size)
        image_array[:, :, 3] = clean_mask

        # ── Step 3: Automatic Outline (optional) ─────────────────────────────
        # Grow the alpha boundary by 1 px and paint it black — instant outline.
        if add_outline:
            image_array = _add_outline(image_array, clean_mask)

        buf = io.BytesIO()
        Image.fromarray(image_array, "RGBA").save(buf, format="PNG")

        return CleanupResult(
            image_bytes=buf.getvalue(),
            alpha_threshold=alpha_threshold,
            min_component_size=min_component_size,
            add_outline=add_outline,
        )

    except Exception as exc:
        raise CleanupError(f"Image cleanup failed: {str(exc)}") from exc