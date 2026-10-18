# ==============================================================================
# PLASTIFY Backend - Production Dockerfile (FastAPI API Service)
# Multi-stage secure build with non-root runtime user
# ==============================================================================

# Stage 1: Build & Dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-warn-script-location -r requirements.txt

# Stage 2: Final Runtime Image
FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/plastify/.local/bin:${PATH}" \
    PYTHONPATH="/app:${PYTHONPATH}"

# Install minimal runtime dependencies (libpq for postgres communication)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Security: run as non-root user
RUN groupadd -g 10001 plastify && \
    useradd -u 10001 -g plastify -m -s /bin/bash plastify

# Copy installed Python packages from builder stage
COPY --from=builder --chown=plastify:plastify /root/.local /home/plastify/.local

# Copy application source code
COPY --chown=plastify:plastify . /app

USER plastify

EXPOSE 8000

# Container orchestration healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health/live || exit 1

# Launch production ASGI server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
