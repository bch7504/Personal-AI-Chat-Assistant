# ---- Stage 1: Build ----
FROM python:3.11-slim AS builder

WORKDIR /app

COPY requirements.lock .
RUN pip install --no-cache-dir --user -r requirements.lock

# ---- Stage 2: Local runtime image ----
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Security: run as non-root user
RUN useradd -m appuser

# Copy installed packages into the runtime user's home so it can execute
# Alembic/Uvicorn without needing access to /root.
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH

# Copy application code
COPY . .

# Windows checkouts can carry CRLF despite the shell-script shebang. Normalize the container copy.
RUN sed -i 's/\r$//' scripts/start_web.sh

# Create data directory with correct ownership
RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import os, urllib.request; port = os.getenv('PORT', '8000'); path = '/internal/v1/health/ready' if os.getenv('WORKSPACE_AGENT_RUNTIME_WORKSPACE_ID') else '/health'; urllib.request.urlopen(f'http://localhost:{port}{path}')" || exit 1

CMD ["/bin/sh", "scripts/start_web.sh"]
