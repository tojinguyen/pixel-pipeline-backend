# 🎮 Pixel Art Processing Pipeline — Python 3.13 Research

Tài liệu nghiên cứu các package, thư viện, và thuật toán Python để build ứng dụng local xử lý ảnh pixel art theo từng bước.

---

## Tổng quan kiến trúc

```
[Next.js Frontend]
      ↕ HTTP / WebSocket
[Python 3.13 FastAPI Backend]
      ↓
┌─────────────────────────────────────────┐
│  Step 1: Background Removal (rembg)     │
│  Step 2: Downscale Nearest Neighbor     │
│  Step 3: Color Palette Indexing         │
│  Step 4: Edge Cleanup / Jaggies        │
└─────────────────────────────────────────┘
```

---

## 📦 Core Dependencies

### Web Framework (Backend)

| Package | Mô tả |
|---|---|
| `fastapi` | REST API framework, async, hỗ trợ file upload |
| `uvicorn` | ASGI server để chạy FastAPI |
| `python-multipart` | Hỗ trợ form/file upload |

```bash
# pip
pip install fastapi uvicorn python-multipart

# uv
uv add fastapi uvicorn python-multipart
```

---

## 🔧 Theo từng bước xử lý

---

### Bước 1 — Xóa nền (Background Removal)

**Thư viện khuyên dùng: `rembg`**

- Chạy hoàn toàn **offline** / local, không cần API key
- Hỗ trợ Python 3.10–3.13 ✅
- Dùng model U2Net và BiRefNet (deep learning)
- Output: PNG có **alpha channel** (nền trong suốt)

```bash
# pip
pip install "rembg[cpu]"

# uv
uv add "rembg[cpu]"
```

**Code demo:**

```python
from rembg import remove, new_session
from PIL import Image
import io

def remove_background(input_bytes: bytes) -> bytes:
    """
    Xóa nền ảnh, trả về PNG với nền trong suốt.
    Session reuse giúp tăng performance khi xử lý nhiều ảnh.
    """
    session = new_session("u2net")  # hoặc "birefnet-general" (chất lượng cao hơn)
    output_bytes = remove(input_bytes, session=session)
    return output_bytes

# Sử dụng
with open("input.jpg", "rb") as f:
    result = remove_background(f.read())

with open("output.png", "wb") as f:
    f.write(result)
```

**Các model có thể dùng:**

| Model | Kích thước | Phù hợp |
|---|---|---|
| `u2net` | ~170MB | General purpose |
| `u2netp` | ~4MB | Nhẹ, nhanh hơn |
| `birefnet-general` | ~370MB | Chất lượng cao nhất |
| `u2net_human_seg` | ~170MB | Người / nhân vật |

---

### Bước 2 — Downscale về độ phân giải pixel art

**Thuật toán: Nearest Neighbor (bắt buộc)**

Nearest Neighbor giữ nguyên độ sắc nét của pixel, không bị blur như Bilinear/Bicubic.

**Thư viện: `Pillow` (PIL)**

```bash
# pip
pip install Pillow

# uv
uv add Pillow
```

**Code demo:**

```python
from PIL import Image

def downscale_nearest_neighbor(
    img: Image.Image,
    target_size: tuple[int, int]  # ví dụ: (64, 64) hoặc (128, 128)
) -> Image.Image:
    """
    Thu nhỏ ảnh dùng thuật toán Nearest Neighbor.
    Giữ cạnh sắc nét, đúng chất pixel art retro.
    """
    return img.resize(target_size, resample=Image.Resampling.NEAREST)

# Sử dụng
img = Image.open("character_no_bg.png")
pixel_img = downscale_nearest_neighbor(img, (64, 64))
pixel_img.save("character_64x64.png")
```

**Các kích thước thường dùng:**

| Kích thước | Dùng cho |
|---|---|
| `16x16` | Icon nhỏ, item |
| `32x32` | Nhân vật nhỏ |
| `64x64` | Nhân vật trung bình |
| `128x128` | Nhân vật lớn, boss |

---

### Bước 3 — Giới hạn bảng màu (Color Palette Indexing)

Mục tiêu: từ hàng ngàn màu gradient của AI → về 8/16/32 màu bệt.

#### Option A: `Pillow` — `quantize()` (đơn giản nhất)

```python
from PIL import Image

def reduce_colors_pillow(img: Image.Image, num_colors: int = 16) -> Image.Image:
    """
    Giảm số màu dùng Pillow quantize.
    Dùng thuật toán median-cut mặc định.
    """
    # Chuyển về RGBA trước khi quantize để giữ transparency
    if img.mode == "RGBA":
        # Tách alpha channel
        r, g, b, a = img.split()
        rgb_img = Image.merge("RGB", (r, g, b))
        quantized = rgb_img.quantize(colors=num_colors, method=Image.Quantize.MEDIANCUT)
        quantized = quantized.convert("RGBA")
        quantized.putalpha(a)
        return quantized
    return img.quantize(colors=num_colors)
```

#### Option B: `OpenCV` + `K-Means Clustering` (chất lượng cao hơn)

```bash
# pip
pip install opencv-python-headless numpy

# uv
uv add opencv-python-headless numpy
```

```python
import cv2
import numpy as np
from PIL import Image

def reduce_colors_kmeans(img: Image.Image, num_colors: int = 16) -> Image.Image:
    """
    Giảm màu dùng K-Means clustering.
    Chất lượng tốt hơn Pillow quantize nhưng chậm hơn.
    """
    img_array = np.array(img)
    has_alpha = img_array.shape[2] == 4 if len(img_array.shape) == 3 else False

    if has_alpha:
        alpha = img_array[:, :, 3]
        rgb = img_array[:, :, :3]
    else:
        rgb = img_array

    # Reshape thành list pixels
    pixels = rgb.reshape(-1, 3).astype(np.float32)

    # K-Means clustering
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2)
    _, labels, centers = cv2.kmeans(
        pixels, num_colors, None, criteria, 10, cv2.KMEANS_RANDOM_CENTERS
    )

    # Map mỗi pixel về màu centroid gần nhất
    centers = np.uint8(centers)
    quantized_pixels = centers[labels.flatten()]
    quantized_rgb = quantized_pixels.reshape(rgb.shape)

    if has_alpha:
        quantized_rgba = np.dstack([quantized_rgb, alpha])
        return Image.fromarray(quantized_rgba, "RGBA")

    return Image.fromarray(quantized_rgb)
```

#### Option C: `pyxelate` — Dùng Bayesian GMM (chất lượng nghệ thuật nhất)

```bash
# pip
pip install git+https://github.com/sedthh/pyxelate.git

# uv (dùng pip trong uv env)
uv pip install git+https://github.com/sedthh/pyxelate.git
```

```python
from pyxelate import Pyx, Pal
from skimage import io

def convert_pyxelate(input_path: str, output_path: str, factor: int = 8, colors: int = 16):
    """
    Convert ảnh thành pixel art dùng Pyxelate.
    factor: độ pixelation (càng lớn càng "to pixel")
    """
    img = io.imread(input_path)
    
    # Có thể dùng palette chuẩn retro
    pixel = Pyx(factor=factor, palette=colors, dither="atkinson").fit_transform(img)
    
    io.imsave(output_path, pixel)

# Dùng palette chuẩn retro (Game Boy, NES, PICO-8, v.v.)
# Pal.GAMEBOY, Pal.NES, Pal.PICO_8, Pal.C64, Pal.APPLE_II_HI
```

#### Option D: `PixelOE` — Thuật toán tiên tiến nhất (contrast-aware)

```bash
# pip
pip install pixeloe

# uv
uv add pixeloe
```

```python
from pixeloe.pixelize import pixelize
from PIL import Image

def convert_pixeloe(input_path: str, output_path: str, target_size: int = 64):
    """
    PixelOE: Giữ chi tiết cạnh tốt nhất, hỗ trợ nhiều mode.
    mode: 'center' | 'contrast' | 'k-centroid' | 'nearest'
    """
    img = Image.open(input_path)
    result = pixelize(
        img,
        target_size=target_size,
        patch_size=16,
        mode="contrast",     # Tốt nhất cho pixel art từ AI
        colors=16,           # Giới hạn màu
    )
    result.save(output_path)
```

---

### Bước 4 — Làm sạch viền (Jaggies Removal & Edge Cleanup)

**Thư viện: `OpenCV` + `scipy`**

```bash
# pip
pip install opencv-python-headless scipy

# uv
uv add opencv-python-headless scipy
```

```python
import cv2
import numpy as np
from PIL import Image

def cleanup_jaggies(img: Image.Image) -> Image.Image:
    """
    Làm sạch pixel thừa ở viền (jaggies).
    Dùng morphological operations.
    """
    img_array = np.array(img)
    
    if img_array.shape[2] == 4:  # RGBA
        alpha = img_array[:, :, 3]
        
        # Tạo binary mask từ alpha channel
        mask = (alpha > 128).astype(np.uint8) * 255
        
        # Morphological closing để lấp lỗ nhỏ
        kernel = np.ones((2, 2), np.uint8)
        mask_closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        
        # Morphological opening để xóa pixel thừa ở rìa
        mask_cleaned = cv2.morphologyEx(mask_closed, cv2.MORPH_OPEN, kernel)
        
        # Áp dụng mask đã cleanup
        img_array[:, :, 3] = mask_cleaned
        
    return Image.fromarray(img_array)

def apply_lospec_palette(img: Image.Image, palette_hex: list[str]) -> Image.Image:
    """
    Áp bảng màu từ Lospec.com vào ảnh.
    palette_hex: list hex colors, ví dụ ["#0f380f", "#306230", ...]
    """
    # Convert hex → RGB
    palette_rgb = []
    for hex_color in palette_hex:
        hex_color = hex_color.lstrip("#")
        palette_rgb.append(tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4)))
    
    palette_flat = [val for color in palette_rgb for val in color]
    # Pad tới 256 màu
    palette_flat.extend([0] * (768 - len(palette_flat)))
    
    # Tạo palette image
    palette_img = Image.new("P", (1, 1))
    palette_img.putpalette(palette_flat)
    
    # Quantize theo palette
    img_rgb = img.convert("RGB")
    quantized = img_rgb.quantize(palette=palette_img)
    return quantized.convert("RGBA")
```

---

## 🚀 FastAPI Backend — Skeleton

```bash
# pip
pip install fastapi uvicorn python-multipart Pillow rembg[cpu] opencv-python-headless pixeloe numpy

# uv (recommended)
uv init pixel-art-backend
cd pixel-art-backend
uv add fastapi uvicorn python-multipart Pillow "rembg[cpu]" opencv-python-headless pixeloe numpy
```

```python
# main.py
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from rembg import remove, new_session
import io

app = FastAPI(title="Pixel Art Pipeline API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js
    allow_methods=["*"],
    allow_headers=["*"],
)

# Khởi tạo session một lần (tránh reload model mỗi request)
rembg_session = new_session("u2net")

@app.post("/api/remove-bg")
async def remove_background(file: UploadFile = File(...)):
    """Bước 1: Xóa nền ảnh"""
    input_bytes = await file.read()
    output_bytes = remove(input_bytes, session=rembg_session)
    return StreamingResponse(io.BytesIO(output_bytes), media_type="image/png")

@app.post("/api/pixelate")
async def pixelate_image(
    file: UploadFile = File(...),
    target_size: int = Form(64),
    num_colors: int = Form(16),
):
    """Bước 2+3: Downscale + Giới hạn màu"""
    input_bytes = await file.read()
    img = Image.open(io.BytesIO(input_bytes)).convert("RGBA")
    
    # Downscale Nearest Neighbor
    pixel_img = img.resize((target_size, target_size), resample=Image.Resampling.NEAREST)
    
    # Quantize màu (giữ alpha)
    r, g, b, a = pixel_img.split()
    rgb_img = Image.merge("RGB", (r, g, b))
    quantized = rgb_img.quantize(colors=num_colors).convert("RGBA")
    quantized.putalpha(a)
    
    output_bytes = io.BytesIO()
    quantized.save(output_bytes, format="PNG")
    output_bytes.seek(0)
    return StreamingResponse(output_bytes, media_type="image/png")

@app.post("/api/full-pipeline")
async def full_pipeline(
    file: UploadFile = File(...),
    target_size: int = Form(64),
    num_colors: int = Form(16),
):
    """Chạy toàn bộ pipeline: Remove BG → Downscale → Quantize"""
    input_bytes = await file.read()
    
    # Step 1: Remove background
    no_bg_bytes = remove(input_bytes, session=rembg_session)
    
    # Step 2: Downscale
    img = Image.open(io.BytesIO(no_bg_bytes)).convert("RGBA")
    pixel_img = img.resize((target_size, target_size), resample=Image.Resampling.NEAREST)
    
    # Step 3: Color quantization
    r, g, b, a = pixel_img.split()
    rgb_img = Image.merge("RGB", (r, g, b))
    quantized = rgb_img.quantize(colors=num_colors).convert("RGBA")
    quantized.putalpha(a)
    
    output_bytes = io.BytesIO()
    quantized.save(output_bytes, format="PNG")
    output_bytes.seek(0)
    return StreamingResponse(output_bytes, media_type="image/png")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
```

---

## 📊 So sánh các thư viện

### Background Removal

| Thư viện | Offline? | Chất lượng | Tốc độ | Python 3.13 |
|---|---|---|---|---|
| `rembg` (u2net) | ✅ | ⭐⭐⭐⭐ | Trung bình | ✅ |
| `rembg` (birefnet) | ✅ | ⭐⭐⭐⭐⭐ | Chậm | ✅ |
| `remove.bg` API | ❌ (cloud) | ⭐⭐⭐⭐⭐ | Nhanh | ✅ |

### Pixel Art Conversion

| Thư viện | Thuật toán | Chất lượng | Tốc độ | Ghi chú |
|---|---|---|---|---|
| `Pillow` | Nearest Neighbor + Quantize | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | Đơn giản, đủ dùng |
| `OpenCV` + K-Means | Clustering | ⭐⭐⭐⭐ | ⭐⭐⭐ | Màu sắc đẹp hơn |
| `pyxelate` | Bayesian GMM | ⭐⭐⭐⭐⭐ | ⭐⭐ | Retro nhất, chậm |
| `PixelOE` | Contrast-Aware | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Tốt nhất cho AI art |

---

## 🗂️ Cấu trúc thư mục đề xuất

```
pixel-art-backend/
├── main.py                  # FastAPI entry point
├── pyproject.toml           # uv dependencies
├── .python-version          # 3.13
├── services/
│   ├── background.py        # rembg service
│   ├── pixelate.py          # downscale + quantize
│   ├── palette.py           # color palette tools
│   └── cleanup.py           # jaggies removal
├── models/
│   └── lospec_palettes.py   # Bảng màu từ Lospec.com
└── uploads/                 # Temp storage
```

---

## 📋 Bảng màu Lospec phổ biến (tham khảo)

```python
# Dán vào models/lospec_palettes.py
PALETTES = {
    "gameboy": ["#0f380f", "#306230", "#8bac0f", "#9bbc0f"],
    "pico8": [
        "#000000", "#1d2b53", "#7e2553", "#008751",
        "#ab5236", "#5f574f", "#c2c3c7", "#fff1e8",
        "#ff004d", "#ffa300", "#ffec27", "#00e436",
        "#29adff", "#83769c", "#ff77a8", "#ffccaa",
    ],
    "nes": [
        "#7C7C7C", "#0000FC", "#0000BC", "#4428BC",
        "#940084", "#A80020", "#A81000", "#881400",
        # ... (thêm đầy đủ 64 màu NES)
    ],
}
```

---

## ⚡ Khởi động nhanh

```bash
# 1. Tạo project với uv
uv init pixel-art-backend --python 3.13
cd pixel-art-backend

# 2. Cài dependencies
uv add fastapi uvicorn python-multipart Pillow "rembg[cpu]" \
       opencv-python-headless numpy pixeloe

# 3. Chạy server
uv run uvicorn main:app --reload --port 8000

# 4. Test API
curl -X POST "http://localhost:8000/api/full-pipeline" \
  -F "file=@character.png" \
  -F "target_size=64" \
  -F "num_colors=16" \
  --output result.png
```
