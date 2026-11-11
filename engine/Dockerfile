# =============================================================================
# Gwei Engine -- multi-stage build
# =============================================================================
# 构建参数(国内机器上构建时用得上,不设就用默认源):
#   --build-arg APT_MIRROR=mirrors.tencentyun.com
#   --build-arg PIP_INDEX_URL=https://mirrors.tencentyun.com/pypi/simple
# =============================================================================

# Stage 1: Builder -- compile C extensions (grpcio, pgvector, etc.)
FROM python:3.12-slim AS builder

ARG APT_MIRROR=""
ARG PIP_INDEX_URL=""

WORKDIR /app

RUN if [ -n "$APT_MIRROR" ]; then \
        for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources; do \
            if [ -f "$f" ]; then \
                sed -i "s|http://deb.debian.org/debian|http://$APT_MIRROR/debian|g" "$f"; \
            fi; \
        done; \
    fi && \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

# 构建上下文为仓库根（见 docker-compose*.yml / .github/workflows/build.yml）
COPY engine/pyproject.toml ./
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip install --no-cache-dir --index-url "$PIP_INDEX_URL" --prefix=/install .; \
    else \
        pip install --no-cache-dir --prefix=/install .; \
    fi

# =============================================================================
# Stage 2: Runtime -- copy only compiled artifacts, no build tools
# =============================================================================
FROM python:3.12-slim AS runtime

ARG APT_MIRROR=""

WORKDIR /app

RUN if [ -n "$APT_MIRROR" ]; then \
        for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources; do \
            if [ -f "$f" ]; then \
                sed -i "s|http://deb.debian.org/debian|http://$APT_MIRROR/debian|g" "$f"; \
            fi; \
        done; \
    fi && \
    apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    postgresql-client \
    redis-tools \
    && rm -rf /var/lib/apt/lists/*

# 可选:docker CLI。只有 dev 把引擎容器当作 harness 启动器时才需要(要挂宿主的 docker.sock);
# 生产镜像不装,构建参数默认 0。
ARG INSTALL_DOCKER_CLI=0
# 官方站在国内常常握手失败,给个可换的下载点(镜像站同样有 static/stable)
ARG DOCKER_CLI_URL="https://download.docker.com/linux/static/stable/x86_64/docker-27.5.1.tgz"
RUN if [ "$INSTALL_DOCKER_CLI" = "1" ]; then \
        curl -fsSL "$DOCKER_CLI_URL" -o /tmp/docker.tgz \
        && tar -xzf /tmp/docker.tgz -C /tmp \
        && install -m 0755 /tmp/docker/docker /usr/local/bin/docker \
        && rm -rf /tmp/docker /tmp/docker.tgz; \
    fi

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY engine/ ./engine/
COPY plugins/ ./plugins/

# Ensure entrypoint is executable
RUN chmod +x engine/entrypoint.sh

# Create non-root user
RUN groupadd -r gwei && useradd -r -g gwei -d /app -s /bin/false gwei \
    && chown -R gwei:gwei /app \
    # harness 工作区:目录先建好并归 gwei,命名卷第一次挂上来会继承这个属主
    && mkdir -p /workspaces && chown gwei:gwei /workspaces

USER gwei

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8000/api/health || exit 1

ENTRYPOINT ["./engine/entrypoint.sh"]
