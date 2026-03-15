import asyncio
import io
import os
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image
from rembg import new_session, remove

from app.core.exceptions import ImageProcessingError

class DitherMethod(str, Enum):
    ORDERED = "ordered"
    FLOYD_STEINBERG = "floyd-steinberg"
    ATKINSON = "atkinson"
    NONE = "none"


# ---------------------------------------------------------------------------
# Data Contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PixelizeResult:
    image_bytes: bytes
    num_colors: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def pixelize_image_async(
    input_bytes: bytes,
    num_colors: int = 16,
    target_size: int = 64,
    dither_method: DitherMethod = DitherMethod.ORDERED,
    dither_strength: float = 0.5,
) -> PixelizeResult:
    """Convert an image to pixel-art quality through a 4-step AI pipeline.

    Steps:
        1. Background removal via birefnet-general + Hard Alpha Binarization
        2. Contrast-Aware Downscaling
        3. CIELAB Color Quantization + Dithering
        4. CCL Orphan Removal + Dilation Outline

    Args:
        input_bytes:     Raw image bytes (PNG / JPEG / WEBP …).
        num_colors:      Target palette size (1–256). Default 16.
        target_size:     Pixel-art grid size (8–512). Default 64.
        dither_method:   "ordered" | "floyd-steinberg" | "atkinson" | "none". Default "ordered".
        dither_strength: Dithering intensity 0.0–1.0. Default 0.5.
    """
    if not (1 <= num_colors <= 256):
        raise ImageProcessingError("num_colors must be between 1 and 256")
    if not (8 <= target_size <= 512):
        raise ImageProcessingError("target_size must be between 8 and 512")
    if not (0.0 <= dither_strength <= 1.0):
        raise ImageProcessingError("dither_strength must be between 0.0 and 1.0")

    return await asyncio.to_thread(
        _process_pixelize,
        input_bytes,
        num_colors,
        target_size,
        dither_method,
        dither_strength,
    )


def build_pixelized_filename(original_filename: str | None, num_colors: int) -> str:
    filename_base = os.path.splitext(os.path.basename(original_filename or ""))[0]
    if not filename_base:
        filename_base = "image"
    return f"{filename_base}_{num_colors}colors.png"


# ---------------------------------------------------------------------------
# Session caching  (rembg model is expensive to initialise)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_rembg_session():
    """Load birefnet-general once and reuse across all requests."""
    return new_session("birefnet-general")


# ---------------------------------------------------------------------------
# Step 1 – Background Removal + Hard Alpha Binarization
# ---------------------------------------------------------------------------

def _remove_background(image: Image.Image) -> Image.Image:
    """Remove background with birefnet-general, then binarise the alpha channel.

    Pixel-art does not tolerate semi-transparent edge pixels (anti-aliasing).
    Every alpha value is snapped to either 0 (transparent) or 255 (opaque).
    """
    buf = io.BytesIO()
    image.save(buf, format="PNG")

    result_bytes = remove(buf.getvalue(), session=_get_rembg_session())
    result = Image.open(io.BytesIO(result_bytes)).convert("RGBA")

    # Hard Alpha Binarization – razor-sharp silhouette, no fringing
    arr = np.array(result)
    alpha = arr[:, :, 3]
    alpha[alpha < 128] = 0
    alpha[alpha >= 128] = 255
    arr[:, :, 3] = alpha

    return Image.fromarray(arr, "RGBA")


# ---------------------------------------------------------------------------
# Step 2 – Contrast-Aware Downscaling (PixelOE)
# ---------------------------------------------------------------------------

def _downscale_contrast_aware(image: Image.Image, target_size: int) -> Image.Image:
    """Shrink the image while preserving structural detail.

    Two-pass approach:
        1. cv2.INTER_AREA  – true area-average downscale.
           Each output pixel is the weighted average of all source pixels
           that fall inside its corresponding block.  This is the correct
           algorithm for shrinking: it preserves shape / silhouette and
           avoids the aliasing of Nearest-Neighbour.

        2. Unsharp mask  – recovers edge crispness softened by averaging.
           sharpened = original * (1 + amount) - blurred * amount
           Brings back thin lines (weapon edges, hair, eye outlines)
           without breaking spatial coherence.

    Alpha is scaled with INTER_NEAREST to keep the hard binary edges from
    Step 1 (Hard Alpha Binarization) intact.
    """
    rgb_array = np.array(image.convert("RGB"), dtype=np.uint8)   # (H, W, 3)
    alpha_array = np.array(image.split()[3], dtype=np.uint8)      # (H, W)

    src_h, src_w = rgb_array.shape[:2]

    # Preserve aspect ratio
    if src_w >= src_h:
        out_w = target_size
        out_h = max(1, round(target_size * src_h / src_w))
    else:
        out_h = target_size
        out_w = max(1, round(target_size * src_w / src_h))

    # Pass 1: area-average downscale — coherent shape, no aliasing
    rgb_small = cv2.resize(rgb_array, (out_w, out_h), interpolation=cv2.INTER_AREA)
    alpha_small = cv2.resize(alpha_array, (out_w, out_h), interpolation=cv2.INTER_NEAREST)

    # Pass 2: unsharp mask — restore edge contrast
    # σ=0.5 keeps the blur tight (1-pixel radius) so only fine edges are sharpened
    blurred = cv2.GaussianBlur(rgb_small, (3, 3), sigmaX=0.5)
    sharpened = cv2.addWeighted(rgb_small, 1.8, blurred, -0.8, 0)
    sharpened = np.clip(sharpened, 0, 255).astype(np.uint8)

    result = Image.fromarray(sharpened, "RGB").convert("RGBA")
    result.putalpha(Image.fromarray(alpha_small, "L"))
    return result


# ---------------------------------------------------------------------------
# Step 3 – CIELAB Color Quantization + Dithering
# ---------------------------------------------------------------------------

# 8×8 Bayer threshold matrix normalised to [0, 1)
_BAYER_8X8 = np.array([
    [ 0, 48, 12, 60,  3, 51, 15, 63],
    [32, 16, 44, 28, 35, 19, 47, 31],
    [ 8, 56,  4, 52, 11, 59,  7, 55],
    [40, 24, 36, 20, 43, 27, 39, 23],
    [ 2, 50, 14, 62,  1, 49, 13, 61],
    [34, 18, 46, 30, 33, 17, 45, 29],
    [10, 58,  6, 54,  9, 57,  5, 53],
    [42, 26, 38, 22, 41, 25, 37, 21],
], dtype=np.float32) / 64.0


def _build_palette_lab(
    lab: np.ndarray, alpha: np.ndarray, num_colors: int
) -> tuple[np.ndarray, np.ndarray]:
    """K-Means on opaque pixels in LAB space → (palette_lab, palette_rgb)."""
    opaque_lab = lab[alpha >= 128].reshape(-1, 3)
    num_colors = min(num_colors, max(1, len(opaque_lab)))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2)
    _, _, palette_lab = cv2.kmeans(
        opaque_lab.astype(np.float32),
        num_colors, None, criteria, 10, cv2.KMEANS_PP_CENTERS,
    )
    palette_rgb = cv2.cvtColor(
        palette_lab.reshape(1, num_colors, 3).astype(np.float32),
        cv2.COLOR_Lab2RGB,
    )
    palette_rgb = np.clip(palette_rgb[0] * 255, 0, 255).astype(np.uint8)
    return palette_lab, palette_rgb


def _nearest_palette_idx(lab_pixels: np.ndarray, palette_lab: np.ndarray) -> np.ndarray:
    """Vectorised nearest-palette lookup via Euclidean distance in LAB."""
    diff = lab_pixels[:, np.newaxis, :] - palette_lab[np.newaxis, :, :]
    return np.argmin(np.sum(diff ** 2, axis=2), axis=1)


def _dither_ordered(
    lab: np.ndarray, palette_lab: np.ndarray, palette_rgb: np.ndarray,
    alpha: np.ndarray, strength: float,
) -> np.ndarray:
    """Bayer 8×8 ordered dithering in LAB space (vectorised)."""
    h, w = lab.shape[:2]
    # Scale strength from [0,1] → [0, 16] LAB shift units
    bayer_map = np.tile(_BAYER_8X8, (h // 8 + 1, w // 8 + 1))[:h, :w]
    offset = (bayer_map[:, :, np.newaxis] - 0.5) * (strength * 16.0)
    lab_shifted = lab + offset
    idx = _nearest_palette_idx(lab_shifted.reshape(-1, 3), palette_lab)
    return palette_rgb[idx].reshape(h, w, 3)


def _dither_floyd_steinberg(
    lab: np.ndarray, palette_lab: np.ndarray, palette_rgb: np.ndarray,
    alpha: np.ndarray, strength: float,
) -> np.ndarray:
    """Floyd-Steinberg error-diffusion dithering in LAB space.

    Distributes quantisation error to 4 neighbours:
        pixel+1     7/16
        pixel-1+row 3/16
        pixel+row   5/16
        pixel+1+row 1/16
    """
    h, w = lab.shape[:2]
    buf = lab.copy().astype(np.float32)        # mutable working copy
    out_rgb = np.zeros((h, w, 3), dtype=np.uint8)

    for y in range(h):
        for x in range(w):
            if alpha[y, x] < 128:
                continue
            old = buf[y, x]
            idx = int(_nearest_palette_idx(old.reshape(1, 3), palette_lab)[0])
            new_lab = palette_lab[idx]
            out_rgb[y, x] = palette_rgb[idx]

            err = (old - new_lab) * strength
            if x + 1 < w:
                buf[y,     x + 1] += err * (7 / 16)
            if y + 1 < h:
                if x - 1 >= 0:
                    buf[y + 1, x - 1] += err * (3 / 16)
                buf[y + 1, x    ] += err * (5 / 16)
                if x + 1 < w:
                    buf[y + 1, x + 1] += err * (1 / 16)

    return out_rgb


def _dither_atkinson(
    lab: np.ndarray, palette_lab: np.ndarray, palette_rgb: np.ndarray,
    alpha: np.ndarray, strength: float,
) -> np.ndarray:
    """Atkinson dithering in LAB space — spreads only 6/8 of the error.

    Produces a higher-contrast, more graphic look than Floyd-Steinberg,
    characteristic of early Mac/Game Boy aesthetics.

    Each pixel distributes 1/8 of its error to 6 neighbours:
        x+1, x+2  (same row)
        x-1, x, x+1  (next row)
        x  (two rows down)
    """
    h, w = lab.shape[:2]
    buf = lab.copy().astype(np.float32)
    out_rgb = np.zeros((h, w, 3), dtype=np.uint8)

    offsets = [(0, 1), (0, 2), (1, -1), (1, 0), (1, 1), (2, 0)]

    for y in range(h):
        for x in range(w):
            if alpha[y, x] < 128:
                continue
            old = buf[y, x]
            idx = int(_nearest_palette_idx(old.reshape(1, 3), palette_lab)[0])
            new_lab = palette_lab[idx]
            out_rgb[y, x] = palette_rgb[idx]

            err = (old - new_lab) * strength * (1 / 8)
            for dy, dx in offsets:
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w:
                    buf[ny, nx] += err

    return out_rgb


def _quantize_cielab_dithered(
    image: Image.Image,
    num_colors: int,
    dither_method: DitherMethod,
    dither_strength: float,
) -> Image.Image:
    """Quantise to num_colors using K-Means in CIELAB + selected dithering."""
    arr = np.array(image, dtype=np.uint8)
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3]
    h, w = rgb.shape[:2]

    rgb_f32 = rgb.astype(np.float32) / 255.0
    lab = cv2.cvtColor(rgb_f32, cv2.COLOR_RGB2Lab)

    palette_lab, palette_rgb = _build_palette_lab(lab, alpha, num_colors)

    if dither_method == "none" or dither_strength == 0.0:
        idx = _nearest_palette_idx(lab.reshape(-1, 3), palette_lab)
        quantized_rgb = palette_rgb[idx].reshape(h, w, 3)
    elif dither_method == "ordered":
        quantized_rgb = _dither_ordered(lab, palette_lab, palette_rgb, alpha, dither_strength)
    elif dither_method == "floyd-steinberg":
        quantized_rgb = _dither_floyd_steinberg(lab, palette_lab, palette_rgb, alpha, dither_strength)
    elif dither_method == "atkinson":
        quantized_rgb = _dither_atkinson(lab, palette_lab, palette_rgb, alpha, dither_strength)
    else:
        raise ImageProcessingError(f"Unknown dither_method: {dither_method!r}")

    result_arr = np.dstack([quantized_rgb, alpha]).astype(np.uint8)
    return Image.fromarray(result_arr, "RGBA")


# ---------------------------------------------------------------------------
# Step 4 – CCL Orphan Removal + Dilation Outline
# ---------------------------------------------------------------------------

# Connected components smaller than this area (px²) are considered noise.
_MIN_COMPONENT_SIZE = 4


def _cleanup_and_outline(image: Image.Image) -> Image.Image:
    """Remove stray pixels via CCL then stamp a 1-pixel black outline.

    CCL Orphan Removal:
        Morphological erosion would round corners and distort the sprite shape.
        Instead, Connected Component Labelling finds isolated 1–3 px "islands"
        and recolours them to match the largest adjacent cluster – preserving
        the overall silhouette.

    Dilation Outline:
        A 1-pixel cross-shaped dilation of the alpha mask creates a rim.
        The rim is painted with the darkest colour in the palette, giving the
        character a clean black outline that hides aliasing artefacts and
        separates the sprite from any game background.
    """
    arr = np.array(image, dtype=np.uint8)
    rgb = arr[:, :, :3].copy()
    alpha = arr[:, :, 3].copy()

    opaque = (alpha >= 128).astype(np.uint8) * 255  # binary mask

    # ------------------------------------------------------------------
    # CCL: identify and recolour orphan pixel clusters
    # ------------------------------------------------------------------
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        opaque, connectivity=8,
    )

    cleaned_opaque = np.zeros_like(opaque)

    for label_id in range(1, num_labels):  # 0 = background
        area = stats[label_id, cv2.CC_STAT_AREA]

        if area >= _MIN_COMPONENT_SIZE:
            cleaned_opaque[labels == label_id] = 255
        else:
            # Recolour each orphan pixel to its dominant opaque neighbour
            ys, xs = np.where(labels == label_id)
            for py, px in zip(ys.tolist(), xs.tolist()):
                neighbour_color = _sample_nearest_opaque_neighbour(
                    rgb, cleaned_opaque, py, px,
                )
                if neighbour_color is not None:
                    rgb[py, px] = neighbour_color
                    cleaned_opaque[py, px] = 255
                # else: leave transparent (genuine edge noise)

    # ------------------------------------------------------------------
    # Dilation Outline: 1-px cross kernel → darkest palette colour
    # ------------------------------------------------------------------
    cross_kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    dilated = cv2.dilate(cleaned_opaque, cross_kernel, iterations=1)
    outline_mask = (dilated > 0) & (cleaned_opaque == 0)  # new border pixels

    darkest_color = _find_darkest_color(rgb, cleaned_opaque)
    rgb[outline_mask] = darkest_color

    # Rebuild alpha: opaque character + outline = 255, everything else = 0
    final_alpha = np.zeros_like(alpha)
    final_alpha[cleaned_opaque == 255] = 255
    final_alpha[outline_mask] = 255

    result_arr = np.dstack([rgb, final_alpha]).astype(np.uint8)
    return Image.fromarray(result_arr, "RGBA")


def _sample_nearest_opaque_neighbour(
    rgb: np.ndarray,
    opaque_mask: np.ndarray,
    py: int,
    px: int,
) -> np.ndarray | None:
    """Return the RGB colour of the first opaque neighbour in a 3×3 window."""
    h, w = opaque_mask.shape
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            ny, nx = py + dy, px + dx
            if 0 <= ny < h and 0 <= nx < w and opaque_mask[ny, nx] == 255:
                return rgb[ny, nx]
    return None


def _find_darkest_color(rgb: np.ndarray, opaque_mask: np.ndarray) -> np.ndarray:
    """Return the darkest RGB colour from the opaque region of the sprite."""
    opaque_pixels = rgb[opaque_mask == 255]
    if len(opaque_pixels) == 0:
        return np.array([0, 0, 0], dtype=np.uint8)

    luminance = (
        0.299 * opaque_pixels[:, 0].astype(np.float32)
        + 0.587 * opaque_pixels[:, 1].astype(np.float32)
        + 0.114 * opaque_pixels[:, 2].astype(np.float32)
    )
    return opaque_pixels[np.argmin(luminance)]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _process_pixelize(
    input_bytes: bytes,
    num_colors: int,
    target_size: int,
    dither_method: DitherMethod,
    dither_strength: float,
) -> PixelizeResult:
    try:
        with Image.open(io.BytesIO(input_bytes)) as src:
            image = src.convert("RGBA")

        original_size = image.size  # (W, H) — restored at the end

        # 1. Background removal + hard alpha binarisation
        image = _remove_background(image)

        # 2. Contrast-aware structural downscaling
        image = _downscale_contrast_aware(image, target_size)

        # 3. CIELAB colour quantisation + dithering
        image = _quantize_cielab_dithered(image, num_colors, dither_method, dither_strength)

        # 4. CCL orphan removal + dilation outline
        image = _cleanup_and_outline(image)

        # 5. Upscale back to original size with NEAREST — preserves hard pixel
        #    boundaries and gives the blocky pixel-art look at full resolution
        image = image.resize(original_size, Image.NEAREST)

        output_buffer = io.BytesIO()
        image.save(output_buffer, format="PNG")

        return PixelizeResult(
            image_bytes=output_buffer.getvalue(),
            num_colors=num_colors,
        )

    except ImageProcessingError:
        raise
    except Exception as exc:
        raise ImageProcessingError(f"Pixelization failed: {exc}") from exc