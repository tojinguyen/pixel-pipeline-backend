import asyncio
import io
import os
from dataclasses import dataclass

from PIL import Image

from app.core.pixelize import PixelizationError, PixelizeMode, resolve_pixelize_mode, get_preset_palette


@dataclass(frozen=True)
class PixelizeResult:
    image_bytes: bytes
    mode: str
    num_colors: int | None
    palette_name: str | None


async def pixelize_image_async(
    input_bytes: bytes,
    mode: str | None = None,
    num_colors: int | None = None,
    palette_name: str | None = None,
) -> PixelizeResult:
    resolved_mode = resolve_pixelize_mode(mode)
    
    # Validation logic
    if resolved_mode == PixelizeMode.AUTO:
        if num_colors is None:
            num_colors = 16
        if num_colors <= 0 or num_colors > 256:
            raise PixelizationError("num_colors must be between 1 and 256")
        palette_name = None
    elif resolved_mode == PixelizeMode.PRESET:
        if not palette_name:
            raise PixelizationError("palette_name is required when mode is 'preset'")
        num_colors = None
        # Validates that palette exists
        get_preset_palette(palette_name)

    return await asyncio.to_thread(
        _process_pixelize,
        input_bytes,
        resolved_mode,
        num_colors,
        palette_name,
    )


def build_pixelized_filename(original_filename: str | None, mode: str, palette_name: str | None, num_colors: int | None) -> str:
    filename_base = os.path.splitext(os.path.basename(original_filename or ""))[0]
    if not filename_base:
        filename_base = "image"
        
    if mode == PixelizeMode.PRESET.value and palette_name:
        return f"{filename_base}_{palette_name}.png"
    elif mode == PixelizeMode.AUTO.value and num_colors:
        return f"{filename_base}_{num_colors}colors.png"
    
    return f"{filename_base}_pixelized.png"


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _process_pixelize(
    input_bytes: bytes,
    mode: PixelizeMode,
    num_colors: int | None,
    palette_name: str | None,
) -> PixelizeResult:
    try:
        with Image.open(io.BytesIO(input_bytes)) as source_image:
            image_rgba = source_image.convert("RGBA")
            r, g, b, a = image_rgba.split()
            image_rgb = Image.merge("RGB", (r, g, b))

            if mode == PixelizeMode.AUTO:
                quantized_rgb = image_rgb.quantize(colors=num_colors, method=Image.Quantize.MEDIANCUT)
                quantized_rgba = quantized_rgb.convert("RGBA")
                quantized_rgba.putalpha(a)
                result_image = quantized_rgba
                
            elif mode == PixelizeMode.PRESET:
                palette_hex = get_preset_palette(palette_name)
                palette_rgb = [_hex_to_rgb(h) for h in palette_hex]
                palette_flat = [val for color in palette_rgb for val in color]
                
                # Pad to 256 colors (768 flat values) required by Pillow putpalette
                palette_flat.extend([0] * (768 - len(palette_flat)))
                
                palette_image = Image.new("P", (1, 1))
                palette_image.putpalette(palette_flat)
                
                # Pillow's quantize down to a specific palette
                # dither=0 usually better for simple pixel art to avoid noise
                quantized_rgb = image_rgb.quantize(palette=palette_image, dither=0)
                quantized_rgba = quantized_rgb.convert("RGBA")
                quantized_rgba.putalpha(a)
                result_image = quantized_rgba

        output_buffer = io.BytesIO()
        result_image.save(output_buffer, format="PNG")
        
        return PixelizeResult(
            image_bytes=output_buffer.getvalue(),
            mode=mode.value,
            num_colors=num_colors,
            palette_name=palette_name
        )
    except Exception as exc:
        raise PixelizationError(f"Image pixelization failed: {str(exc)}") from exc