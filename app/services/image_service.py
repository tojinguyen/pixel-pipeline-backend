import asyncio
import numpy as np
from PIL import Image
import io
import os
import re
import uuid
import cv2

async def remove_background_async(input_bytes: bytes, session) -> bytes:
    """
    Upgraded pipeline:
      1. birefnet-general background removal
      2. Hard Alpha Binarization (0 or 255 only)
      3. Alpha Erosion (1px cross kernel) — strips contaminated fringe pixels
      4. Fringe Decontamination — fixes RGB color bleed on surviving edge pixels
    """
    def _remove_and_clean(data: bytes, sess) -> bytes:
        from rembg import remove

        # ── Step 1: AI background removal ──────────────────────────────────
        removed_bytes = remove(data, session=sess)
        img = Image.open(io.BytesIO(removed_bytes)).convert("RGBA")
        arr = np.array(img, dtype=np.uint8)

        # ── Step 2: Hard Alpha Binarization ────────────────────────────────
        alpha = arr[:, :, 3]
        alpha[alpha < 128] = 0
        alpha[alpha >= 128] = 255
        arr[:, :, 3] = alpha

        # ── Step 3: Alpha Erosion (1px cross kernel) ───────────────────────
        # Eat away the outermost ring of opaque pixels — these are the ones
        # whose RGB color was blended with the removed background.
        # Cross kernel matches the Dilation kernel used later for outlining.
        cross_kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
        eroded_alpha = cv2.erode(alpha, cross_kernel, iterations=1)
        arr[:, :, 3] = eroded_alpha

        # ── Step 4: Fringe Decontamination ─────────────────────────────────
        # After erosion, new edge pixels may still carry color bleed from
        # the previous outer ring. Fix by replacing each edge pixel's RGB
        # with its nearest fully-interior neighbor's color.
        #
        # "Edge pixel" = opaque pixel that has at least one transparent neighbor.
        opaque_mask = eroded_alpha == 255

        # Detect edge pixels via dilation diff
        dilated = cv2.dilate(eroded_alpha, cross_kernel, iterations=1)
        edge_mask = (dilated == 255) & ~opaque_mask  # transparent pixels just outside
        # We actually want: opaque pixels adjacent to transparent ones
        transparent_mask = eroded_alpha == 0
        dilated_transparent = cv2.dilate(
            transparent_mask.astype(np.uint8) * 255, cross_kernel, iterations=1
        )
        fringe_mask = opaque_mask & (dilated_transparent == 255)

        if fringe_mask.any():
            # For each fringe pixel, sample color from the nearest interior pixel
            # (interior = opaque AND not a fringe pixel)
            interior_mask = opaque_mask & ~fringe_mask

            # Distance transform: find nearest interior pixel for each fringe pixel
            interior_inv = (~interior_mask).astype(np.uint8)
            _, nearest_pt = cv2.distanceTransformWithLabels(
                interior_inv, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL
            )

            # Build a flat index lookup
            _, w = arr.shape[:2]
            flat_coords = nearest_pt.ravel() - 1  # distanceTransformWithLabels is 1-indexed
            nearest_rows = flat_coords // w
            nearest_cols = flat_coords % w

            fringe_rows, fringe_cols = np.where(fringe_mask)
            fringe_flat = fringe_rows * w + fringe_cols

            arr[fringe_rows, fringe_cols, :3] = arr[
                nearest_rows[fringe_flat], nearest_cols[fringe_flat], :3
            ]

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
