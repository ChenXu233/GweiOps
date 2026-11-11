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

# 构建上下文为仓库根（见 docker-compose*.yml / .github/workflows/build.yml）
COPY engine/pyproject.toml ./
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

# 可选:docker CLI。只有 dev 把引擎容器当作 harness 启动器时才需要(要挂宿主的 docker.sock);
# 生产镜像不装,构建参数默认 0。
ARG INSTALL_DOCKER_CLI=0
RUN if [ "$INSTALL_DOCKER_CLI" = "1" ]; then \
        curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-27.5.1.tgz -o /tmp/docker.tgz \
        && tar -xzf /tmp/docker.tgz -C /tmp \
        && install -m 0755 /tmp/docker/docker /usr/local/bin/docker \
        && rm -rf /tmp/docker /tmp/docker.tgz; \
    fi

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code（engine 包 + plugins 目录,插件是运行时的组成部分）
COPY engine/ ./engine/
COPY plugins/ ./plugins/

# Ensure entrypoint is executable
RUN chmod +x engine/entrypoint.sh

# Create non-root user
RUN groupadd -r gwei && useradd -r -g gwei -d /app -s /bin/false gwei \
    && chown -R gwei:gwei /app
USER gwei

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8000/api/health || exit 1

ENTRYPOINT ["./engine/entrypoint.sh"]