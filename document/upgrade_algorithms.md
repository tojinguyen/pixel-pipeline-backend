# Pipeline Chuyển Đổi Ảnh AI Thành Pixel Art - Đỉnh Cao Chất Lượng

Dưới đây là bản tóm tắt những sự lựa chọn tốt nhất hiện nay để đảm bảo output trông giống như được vẽ tay bởi một họa sĩ pixel thực thụ, sẵn sàng đưa thẳng vào Game Engine.

---

## Bước 1: Bóc Tách Nền & Xử Lý Viền (Background Removal)

**Model AI Tốt Nhất:** `birefnet-general` (chạy qua thư viện `rembg`)

### Tại sao đây là số 1?

Khác với u2net (chỉ cắt mảng lớn), **birefnet** (Bilateral Reference Network) có khả năng nhận diện độ sâu và chi tiết cực nhỏ:
- Sợi tóc
- Vũ khí mảnh
- Ngón tay

Nó trả về mask alpha chính xác gần như tuyệt đối ở mép nhân vật.

### Bí Quyết Chất Lượng: Hard Alpha Binarization

Pixel Art **không được phép** có pixel bán trong suốt ở viền (anti-aliasing). Sau khi model AI bóc nền xong, phải ép toán học toàn bộ kênh Alpha về 2 trạng thái:
- Đục 100% (255)
- Trong suốt 100% (0)

**Công thức:**
```python
mask[mask < 128] = 0
mask[mask >= 128] = 255
```

Việc này tạo ra đường cắt viền sắc như dao cạo, là tiền đề bắt buộc cho các bước sau.

---

## Bước 2: Thu Nhỏ Cấu Trúc Ảnh (Structural Downscaling)

**Thuật Toán Tốt Nhất:** Contrast-Aware Downscaling (sử dụng package `PixelOE` ở chế độ `mode="contrast"`)

### Tại sao đây là số 1?

Thuật toán **Nearest Neighbor** truyền thống bị mù cấu trúc:
- Nó ném bỏ pixel một cách ngẫu nhiên theo lưới grid
- Làm đứt đoạn các chi tiết mảnh như dây chuyền, viền mắt

Ngược lại, thuật toán của PixelOE sẽ:
- Quét qua các block pixel
- Đánh giá độ tương phản (contrast)
- Quyết định giữ lại pixel mang nhiều thông tin nhất

**Kết quả:** Khi thu nhỏ về 64x64, mọi đường nét mảnh (line art) và chi tiết quan trọng đều được bảo toàn trọn vẹn.

---

## Bước 3: Ép Bảng Màu & Tạo Khối (Color Indexing & Shading)

**Thuật Toán Tốt Nhất:** CIELAB Color Space Mapping kết hợp Ordered Dithering

### Tại sao đây là số 1?

#### CIELAB thay vì RGB (K-Means)

**Tuyệt đối không dùng OpenCV K-Means** (hệ RGB) vì:
- Nó sẽ tạo ra màu "bùn" (nhợt nhạt, thiếu sức sống)

**Phải convert sang không gian màu LAB (CIELAB):**
- Mô phỏng chính xác cách mắt người cảm nhận độ sáng và sắc tố
- Khi áp bảng màu (ví dụ Gameboy, NES, Lospec), tính toán khoảng cách Euclidean trên không gian LAB sẽ chọn ra màu chính xác và rực rỡ nhất

#### Dithering: Tạo Khối Ảo

Ảnh AI có gradient mịn. Khi ép về 16 màu, màu sẽ bị gãy vằn vện (banding).

**Thuật toán Bayer Ordered Dithering** (lưới rải hạt):
- Trộn các pixel màu đan xen nhau theo quy luật bàn cờ
- Tạo ảo giác cho mắt người về một màu trung gian chuyển tiếp cực kỳ mượt mà
- Mang đậm chất Retro

---

## Bước 4: Dọn Rác & Bọc Viền (Edge Cleanup & Outlining)

**Thuật Toán Tốt Nhất:** Connected Component Labeling (CCL) để xóa rác + Dilation để bọc viền đen

### Tại sao đây là số 1?

#### Xóa Pixel Mồ Côi (Orphan Removal)

- **Bỏ ngay Morphology** (nó làm cùn các góc nhọn, hỏng shape nhân vật)
- Sử dụng **CCL** (OpenCV Labeling) để quét toàn bộ ảnh
- Tìm ra các "hòn đảo" màu bị cô lập chỉ có kích thước 1x1 hoặc 1x2 pixel
- Noise do quá trình downscale để lại

Thuật toán sẽ cưỡng ép các pixel rác này đổi màu theo cụm pixel lớn nhất bao quanh nó.

**Kết quả:** Mảng màu cực kỳ sạch sẽ (color blocking hoàn hảo)

#### Bọc Viền Tự Động (Automatic Outlining)

Vũ khí tối thượng của Game Asset:
- Dùng thuật toán **Dilation** (giãn nở) trên kênh Alpha
- Chỉ nở đúng 1 pixel theo hình chữ thập (Cross Kernel)
- Lấy phần viền vừa nở ra đó tô thành màu đen/màu tối nhất trong bảng màu

**Nhân vật lập tức có:**
- Một đường viền outline bao quanh
- Che đậy mọi khiếm khuyết răng cưa ở viền
- Tách bạch hẳn khỏi background trong game

---

## Tổng Kết: Pipeline Tối Ưu

```
AI birefnet (Cắt nền)
    ↓
Ép viền đục 100% (Hard Alpha Binarization)
    ↓
PixelOE Contrast-Aware (Thu nhỏ)
    ↓
Giữ nét mảnh
    ↓
Không gian màu LAB + Dithering
    ↓
Ép màu Retro không bị bùn
    ↓
Thuật toán CCL (Xóa pixel rác)
    ↓
Thêm viền Outline bao ngoài
```

