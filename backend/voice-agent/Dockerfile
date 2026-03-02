# Voice Agent Pipeline Container for AWS ECS Fargate
# Build: docker build -t voice-agent .
#
# This container runs pipecat directly with asyncio.run() - the pattern
# pipecat is designed for. Unlike FastAPI-based approaches, this ensures
# all of pipecat's internal async tasks execute properly.
#
# Multi-stage build: build stage compiles any native extensions,
# runtime stage contains only what's needed to run the application.
# Note: pipecat v0.0.102 uses ONNX Runtime for Silero VAD (not PyTorch),
# so torch/torchaudio are not needed.

# ========================
# Stage 1: Build / Install
# ========================
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build tools for any native extensions (gcc, python3-dev)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies into a virtual env for clean copy
RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt

# ========================
# Stage 2: Runtime
# ========================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Runtime-only system dependencies (no gcc/python3-dev)
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Audio processing
    libsndfile1 \
    ffmpeg \
    # Networking (health checks)
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

# Set working directory
WORKDIR /app

# Copy virtual env with installed packages from builder
COPY --from=builder /app/venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Copy application code
COPY app/ ./app/

# Entry point script that handles both service and task modes
# SERVICE_MODE=true: Run HTTP server (always-on, handles multiple calls)
# SERVICE_MODE=false/unset: Run single task (legacy mode, one call per container)
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Change ownership to non-root user
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port 8080 for service mode (HTTP server for receiving call requests)
EXPOSE 8080

CMD ["/app/entrypoint.sh"]
