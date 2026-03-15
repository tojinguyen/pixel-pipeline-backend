import asyncio
import io
import os
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
from PIL import Image
from skimage import color as skcolor

from app.core.exceptions import ImageProcessingError

# ---------------------------------------------------------------------------
# Bayer 4×4 ordered dithering threshold matrix (normalized 0–1)
# ---------------------------------------------------------------------------
_BAYER_4x4 = np.array(
    [
        [0,  8,  2, 10],
        [12, 4, 14,  6],
        [3,  11, 1,  9],
        [15, 7, 13,  5],
    ],
    dtype=np.float32,
) / 16.0


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DownscaleResult:
    image_bytes: bytes
    output_width: int
    output_height: int


# ---------------------------------------------------------------------------
# Pipeline config (optional — all have sensible defaults)
# ---------------------------------------------------------------------------
@dataclass
class PixelArtConfig:
    """Tuning knobs for the full pixel-art conversion pipeline.

    Args:
        num_colors:     Number of palette colors to quantize down to (e.g. 16).
        palette:        Optional custom RGB palette as list[(R,G,B)].
                        When None, an adaptive palette is derived via
                        K-Means clustering in LAB space.
        add_outline:    Whether to draw a 1-px outline around the character.
        outline_color:  RGBA tuple for the outline.  None → darkest palette color.
        orphan_max_size: Connected-component clusters ≤ this area (px²) are
                         recoloured to match their dominant neighbour.
    """

    num_colors: int = 16
    palette: Optional[list[tuple[int, int, int]]] = None
    add_outline: bool = True
    outline_color: Optional[tuple[int, int, int, int]] = None
    orphan_max_size: int = 2


# ---------------------------------------------------------------------------
# Public async entry-point
# ---------------------------------------------------------------------------
async def downscale_image_async(
    input_bytes: bytes,
    target_width: int,
    target_height: int,
    config: Optional[PixelArtConfig] = None,
) -> DownscaleResult:
    return await asyncio.to_thread(
        _downscale_image,
        input_bytes,
        target_width,
        target_height,
        config or PixelArtConfig(),
    )


def build_downscaled_filename(
    original_filename: str | None,
    target_width: int,
    target_height: int,
) -> str:
    filename_base = os.path.splitext(os.path.basename(original_filename or ""))[0]
    if not filename_base:
        filename_base = "image"
    return f"{filename_base}_{target_width}x{target_height}.png"


# ---------------------------------------------------------------------------
# Main synchronous pipeline
# ---------------------------------------------------------------------------
def _downscale_image(
    input_bytes: bytes,
    target_width: int,
    target_height: int,
    config: PixelArtConfig,
) -> DownscaleResult:
    try:
        # ── Load ──────────────────────────────────────────────────────────
        with Image.open(io.BytesIO(input_bytes)) as src:
            src_rgba = src.convert("RGBA")

        arr = np.array(src_rgba, dtype=np.uint8)

        # ── Step 1: Hard Alpha Binarization ───────────────────────────────
        arr[:, :, 3] = _hard_alpha_binarize(arr[:, :, 3])

        # ── Step 2: Contrast-Aware Downscaling (PixelOE) ──────────────────
        src_rgba = Image.fromarray(arr, "RGBA")
        downscaled = _contrast_aware_downscale(src_rgba, target_width, target_height)
        arr = np.array(downscaled, dtype=np.uint8)

        # ── Step 3 + 4: CIELAB Quantization + Bayer Dithering ────────────
        opaque_mask = arr[:, :, 3] == 255

        if opaque_mask.any():
            rgb_f32 = arr[:, :, :3].astype(np.float32) / 255.0

            palette_rgb = (
                np.array(config.palette, dtype=np.float32) / 255.0
                if config.palette
                else _adaptive_palette_lab(rgb_f32, opaque_mask, config.num_colors)
            )
            lab_palette = _rgb_to_lab_palette(palette_rgb)

            dithered = _bayer_dither(rgb_f32, lab_palette, palette_rgb)
            arr[:, :, :3] = (dithered * 255).round().astype(np.uint8)
            arr[~opaque_mask] = [0, 0, 0, 0]  # restore transparency

        # ── Step 5: CCL Orphan Pixel Removal ─────────────────────────────
        arr = _remove_orphan_pixels(arr, max_size=config.orphan_max_size)

        # ── Step 6: Dilation Outline ──────────────────────────────────────
        if config.add_outline:
            outline_rgba = config.outline_color or _darkest_palette_color(palette_rgb)
            arr = _add_outline(arr, outline_rgba)

        # ── Encode ────────────────────────────────────────────────────────
        buf = io.BytesIO()
        Image.fromarray(arr, "RGBA").save(buf, format="PNG")

        return DownscaleResult(
            image_bytes=buf.getvalue(),
            output_width=target_width,
            output_height=target_height,
        )
    except ImageProcessingError:
        raise
    except Exception as exc:
        raise ImageProcessingError("Pixel-art downscaling pipeline failed") from exc


# ---------------------------------------------------------------------------
# Step 1 — Hard Alpha Binarization
# ---------------------------------------------------------------------------
def _hard_alpha_binarize(alpha: np.ndarray) -> np.ndarray:
    """Collapse semi-transparent pixels → fully opaque or fully transparent.

    Pixel art must not contain anti-aliasing on edges.
    Threshold: α < 128 → 0 (transparent), α ≥ 128 → 255 (opaque).
    """
    out = alpha.copy()
    out[out < 128] = 0
    out[out >= 128] = 255
    return out


# ---------------------------------------------------------------------------
# Step 2 — Contrast-Aware Downscaling via PixelOE
# ---------------------------------------------------------------------------
def _contrast_aware_downscale(
    image: Image.Image,
    target_w: int,
    target_h: int,
    patch_size: int = 8,
) -> Image.Image:
    """Contrast-aware downscaling — no torch / pixeloe required.

    For each output pixel, the source image is divided into
    ``patch_size × patch_size`` blocks.  Instead of averaging all
    pixels in the block (which blurs edges) or picking the centre pixel
    (which misses detail), we select whichever pixel has the **highest
    local contrast** — i.e. the pixel whose neighbourhood has the
    greatest luminance variance.  This preserves thin lines, hair
    strands, and weapon silhouettes that Nearest Neighbour would drop.

    Algorithm (replicates PixelOE "contrast" mode without torch):
      1. Convert RGBA → greyscale luminance for contrast scoring only.
      2. Compute per-pixel local variance in a 3×3 window (cv2.boxFilter).
      3. For each (patch_h × patch_w) block that maps to one output pixel,
         pick the source pixel with maximum variance score.
      4. Copy that pixel's full RGBA value to the output.

    Args:
        image:      PIL RGBA image (alpha already binarised).
        target_w:   Canvas width.
        target_h:   Canvas height.
        patch_size: Source pixels collapsed into each output pixel.
                    Smaller = more detail, larger = more stylised.
    """
    orig_w, orig_h = image.size

    # ── Aspect-ratio-preserving output size ───────────────────────────
    scale = min(target_w / orig_w, target_h / orig_h)
    new_w = max(1, round(orig_w * scale))
    new_h = max(1, round(orig_h * scale))

    # ── Pad source to an exact multiple of patch_size ─────────────────
    pad_w = (patch_size - orig_w % patch_size) % patch_size
    pad_h = (patch_size - orig_h % patch_size) % patch_size
    padded_w = orig_w + pad_w
    padded_h = orig_h + pad_h

    src = np.array(image, dtype=np.uint8)                           # (H, W, 4)
    if pad_w or pad_h:
        src = np.pad(src, ((0, pad_h), (0, pad_w), (0, 0)))        # pad with 0 (transparent)

    # ── Luminance for contrast scoring (rec. 601) ─────────────────────
    gray = (
        0.299 * src[:, :, 0].astype(np.float32)
        + 0.587 * src[:, :, 1].astype(np.float32)
        + 0.114 * src[:, :, 2].astype(np.float32)
    )

    # Local variance ≈ E[x²] − E[x]²  via two box filters
    mean   = cv2.boxFilter(gray,          cv2.CV_32F, (3, 3), normalize=True)
    mean_sq = cv2.boxFilter(gray * gray,  cv2.CV_32F, (3, 3), normalize=True)
    variance = mean_sq - mean * mean                                # (H_pad, W_pad)

    # ── Per-block argmax selection ────────────────────────────────────
    # Reshape into (n_blocks_h, patch_h, n_blocks_w, patch_w)
    blocks_h = padded_h // patch_size
    blocks_w = padded_w // patch_size

    var_blocks = variance.reshape(blocks_h, patch_size, blocks_w, patch_size)
    src_blocks = src.reshape(blocks_h, patch_size, blocks_w, patch_size, 4)

    # Flatten each block → (blocks_h, blocks_w, patch_size²)
    var_flat = var_blocks.transpose(0, 2, 1, 3).reshape(blocks_h, blocks_w, -1)
    src_flat = src_blocks.transpose(0, 2, 1, 3, 4).reshape(blocks_h, blocks_w, -1, 4)

    best_idx = np.argmax(var_flat, axis=-1)                         # (blocks_h, blocks_w)
    bh, bw = np.indices((blocks_h, blocks_w))
    output_full = src_flat[bh, bw, best_idx]                       # (blocks_h, blocks_w, 4)

    # ── Crop back to (new_h, new_w) and centre on canvas ─────────────
    output_full = output_full[:new_h, :new_w].astype(np.uint8)

    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    canvas.paste(
        Image.fromarray(output_full, "RGBA"),
        ((target_w - new_w) // 2, (target_h - new_h) // 2),
    )
    return canvas


# ---------------------------------------------------------------------------
# Step 3 — CIELAB palette helpers
# ---------------------------------------------------------------------------
def _rgb_to_lab_palette(palette_rgb: np.ndarray) -> np.ndarray:
    """Convert (N, 3) float32 RGB [0–1] palette → LAB."""
    return skcolor.rgb2lab(palette_rgb.reshape(1, -1, 3)).reshape(-1, 3)


def _adaptive_palette_lab(
    rgb: np.ndarray,
    opaque_mask: np.ndarray,
    num_colors: int,
) -> np.ndarray:
    """Derive palette via K-Means clustering in LAB space.

    Running K-Means in LAB (not RGB) avoids perceptually uneven clusters
    that produce washed-out "mud" colours.

    Returns:
        np.ndarray of shape (num_colors, 3), dtype float32, values in [0, 1].
    """
    pixels_rgb = rgb[opaque_mask]  # (M, 3)
    pixels_lab = skcolor.rgb2lab(pixels_rgb.reshape(1, -1, 3)).reshape(-1, 3).astype(np.float32)

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 200, 0.1)
    _, _, centers_lab = cv2.kmeans(
        pixels_lab,
        num_colors,
        None,
        criteria,
        10,
        cv2.KMEANS_PP_CENTERS,
    )  # (num_colors, 3)

    centers_rgb = skcolor.lab2rgb(centers_lab.reshape(1, -1, 3)).reshape(-1, 3)
    return np.clip(centers_rgb.astype(np.float32), 0.0, 1.0)


# ---------------------------------------------------------------------------
# Step 4 — Bayer Ordered Dithering
# ---------------------------------------------------------------------------
def _bayer_dither(
    rgb: np.ndarray,
    lab_palette: np.ndarray,
    palette_rgb: np.ndarray,
) -> np.ndarray:
    """Apply Bayer 4×4 ordered dithering in LAB space.

    Instead of hard-snapping each pixel to its nearest palette colour,
    a small structured threshold is added first. This makes neighbouring
    pixels alternate between two close palette colours, creating the
    illusion of an intermediate tone — the classic Retro pixel aesthetic.

    Args:
        rgb:         (H, W, 3) float32 image in [0, 1].
        lab_palette: (N, 3) LAB palette.
        palette_rgb: (N, 3) RGB palette [0, 1], same order.

    Returns:
        (H, W, 3) float32 quantised image.
    """
    H, W, _ = rgb.shape

    # Tile the Bayer matrix to cover the full image
    bayer = np.tile(_BAYER_4x4, (H // 4 + 1, W // 4 + 1))[:H, :W]  # (H, W)

    # Perturbation scale = one palette step ≈ avoids over-dithering
    scale = 1.0 / (len(palette_rgb) + 1)
    offset = (bayer - 0.5) * scale  # centred at zero

    dithered_rgb = np.clip(rgb + offset[:, :, None], 0.0, 1.0)

    # Quantise in LAB space: find nearest palette entry per pixel
    indices = _nearest_palette_lab(dithered_rgb, lab_palette)
    return palette_rgb[indices]


def _nearest_palette_lab(rgb: np.ndarray, lab_palette: np.ndarray) -> np.ndarray:
    """Return palette index of the nearest LAB colour for every pixel.

    Args:
        rgb:         (H, W, 3) float32.
        lab_palette: (N, 3) LAB.

    Returns:
        (H, W) int array of palette indices.
    """
    H, W, _ = rgb.shape
    lab_img = skcolor.rgb2lab(rgb).reshape(-1, 3)  # (H*W, 3)

    # Euclidean distance to each palette entry — perceptually uniform in LAB
    diff = lab_img[:, None, :] - lab_palette[None, :, :]  # (H*W, N, 3)
    dist = np.einsum("ijk,ijk->ij", diff, diff)            # (H*W, N)  squared L2
    return np.argmin(dist, axis=1).reshape(H, W)


# ---------------------------------------------------------------------------
# Step 5 — CCL Orphan Pixel Removal
# ---------------------------------------------------------------------------
def _remove_orphan_pixels(rgba: np.ndarray, max_size: int = 2) -> np.ndarray:
    """Eliminate isolated colour clusters left behind by downscaling noise.

    For every unique colour, run Connected Component Labeling (4-connectivity).
    Any component whose area ≤ max_size pixels is recoloured to match the
    dominant colour among its immediate neighbours.

    Avoids Morphology (erosion/dilation on the full image) which rounds
    sharp corners and degrades character silhouettes.
    """
    result = rgba.copy()
    alpha = rgba[:, :, 3]
    rgb = rgba[:, :, :3]
    opaque = (alpha == 255)

    unique_colors = np.unique(rgb[opaque].reshape(-1, 3), axis=0)
    cross_kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))

    for color in unique_colors:
        color_mask = (
            np.all(rgb == color, axis=-1) & opaque
        ).astype(np.uint8)

        n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
            color_mask, connectivity=4
        )

        for lbl in range(1, n_labels):
            area = stats[lbl, cv2.CC_STAT_AREA]
            if area > max_size:
                continue

            component = labels == lbl

            # Dilate the component to find its immediate neighbours
            dilated = cv2.dilate(component.astype(np.uint8), cross_kernel)
            neighbor_mask = (dilated == 1) & (~component) & opaque

            if not neighbor_mask.any():
                continue

            # Pick the most frequent neighbour colour
            neighbor_colors = rgb[neighbor_mask]
            unique_n, counts = np.unique(
                neighbor_colors.reshape(-1, 3), axis=0, return_counts=True
            )
            best_color = unique_n[np.argmax(counts)]
            result[component, :3] = best_color

    return result


# ---------------------------------------------------------------------------
# Step 6 — Dilation Outline
# ---------------------------------------------------------------------------
def _add_outline(
    rgba: np.ndarray,
    outline_color: tuple[int, int, int, int] = (0, 0, 0, 255),
) -> np.ndarray:
    """Draw a 1-pixel outline around the character silhouette.

    Algorithm:
      1. Binary mask of opaque pixels.
      2. Dilate by 1 px using a Cross kernel (no diagonal bleed).
      3. The ring between dilated mask and original mask becomes the outline.

    The cross kernel ensures the outline expands exactly 1 px in NSEW
    directions — clean, predictable, game-asset-ready.
    """
    alpha = rgba[:, :, 3]
    binary = (alpha == 255).astype(np.uint8)

    kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    dilated = cv2.dilate(binary, kernel, iterations=1)

    outline_mask = (dilated == 1) & (binary == 0)

    result = rgba.copy()
    result[outline_mask] = outline_color
    return result


def _darkest_palette_color(
    palette_rgb: np.ndarray,
) -> tuple[int, int, int, int]:
    """Return the perceptually darkest colour in the palette as RGBA."""
    lab = skcolor.rgb2lab(palette_rgb.reshape(1, -1, 3)).reshape(-1, 3)
    darkest_idx = int(np.argmin(lab[:, 0]))  # L* channel
    r, g, b = (palette_rgb[darkest_idx] * 255).round().astype(int)
    return (int(r), int(g), int(b), 255)