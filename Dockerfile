FROM python:3.13-slim

WORKDIR /workspace

# Install uv
RUN pip install --no-cache-dir uv

# Copy dependency manifests first (layer caching)
COPY pyproject.toml .
COPY uv.lock .

# Install production dependencies
RUN uv sync --no-dev

# Copy source code
COPY app/ app/
COPY main.py .

# Add venv to PATH so uv-installed packages are available
ENV PATH="/workspace/.venv/bin:$PATH"

EXPOSE 8000

# Production command (overridden in docker-compose for dev hot-reload)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
