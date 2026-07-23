# =============================================================================
# Gwei Engine -- multi-stage build
# =============================================================================

# Stage 1: Builder -- compile C extensions (grpcio, pgvector, etc.)
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

# =============================================================================
# Stage 2: Runtime -- copy only compiled artifacts, no build tools
FROM python:3.12-slim AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    postgresql-client \
    redis-tools \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Ensure entrypoint is executable
RUN chmod +x entrypoint.sh

# Create non-root user
RUN groupadd -r gwei && useradd -r -g gwei -d /app -s /bin/false gwei \
    && chown -R gwei:gwei /app
USER gwei

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8000/api/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]