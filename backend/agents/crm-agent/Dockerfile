# CRM Capability Agent
# Lightweight container for Strands A2A agent with CRM API integration
#
# Build: docker build -t crm-agent .
# Run:   docker run -p 8000:8000 -e CRM_API_URL=... crm-agent

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY crm_client.py .
COPY main.py .

# Ownership
RUN chown -R appuser:appuser /app
USER appuser

# Default port for A2A server
EXPOSE 8000

# Health check via the A2A Agent Card endpoint (Strands A2AServer has no /health route)
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/.well-known/agent-card.json || exit 1

CMD ["python", "main.py"]
