# ==========================================
# STAGE 1: BUILDER (Cài đặt & Tải Model)
# ==========================================
FROM python:3.13-slim AS builder

# Dùng luôn image của UV thay vì cài qua pip để tối ưu tốc độ
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /workspace

# Chỉ cài curl để tải model (bỏ git vì không cần clone pixeloe nữa)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates

# Tải sẵn model RemBG (Tuyệt đối không tải lúc runtime)
RUN mkdir -p /root/.u2net && \
    curl -L https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx -o /root/.u2net/u2netp.onnx

# Copy file config để cài package
COPY pyproject.toml uv.lock ./

# Cài đặt package vào thư mục ảo .venv
# Tham số --no-install-project giúp tận dụng cache Docker tốt hơn
RUN uv sync --no-dev --no-install-project

# ==========================================
# STAGE 2: RUNNER (Image chạy thực tế cực nhẹ)
# ==========================================
FROM python:3.13-slim

WORKDIR /workspace

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Chỉ cài ĐÚNG 2 thư viện C bắt buộc để chạy OpenCV, không chứa curl/git rác
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# Copy môi trường Python (.venv) từ Builder sang
COPY --from=builder /workspace/.venv /workspace/.venv

# Copy Model đã tải sẵn từ Builder sang
COPY --from=builder /root/.u2net /root/.u2net

# Copy source code của bạn
COPY app/ app/
COPY main.py alembic.ini ./
COPY backend_migrations/ backend_migrations/
COPY scripts/ scripts/
RUN chmod +x scripts/*.sh

# Đưa .venv vào PATH
ENV PATH="/workspace/.venv/bin:$PATH"

EXPOSE 8000

ENTRYPOINT ["./scripts/start.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]