#!/bin/sh
# =============================================================================
# Gwei Engine — 启动入口
# 职责：等数据库就绪 → 执行迁移 → 启动 uvicorn
# $@ 透传给 uvicorn（dev 传 --reload）
# =============================================================================
set -e

# 等待 PostgreSQL
echo "Waiting for PostgreSQL..."
while ! pg_isready -h "$POSTGRES_HOST" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-gwei}" >/dev/null 2>&1; do
    sleep 1
done
echo "PostgreSQL is ready."

# 等待 Redis
echo "Waiting for Redis..."
while ! redis-cli -h "$REDIS_HOST" -p "${REDIS_PORT:-6379}" ping >/dev/null 2>&1; do
    sleep 1
done
echo "Redis is ready."

# 执行数据库迁移
echo "Running Alembic migrations..."
alembic upgrade head

# 启动 uvicorn，$@ 传入额外参数（如 --reload）
exec uvicorn engine.api.app:app \
    --host 0.0.0.0 \
    --port 8000 \
    --proxy-headers \
    --forwarded-allow-ips='*' \
    "$@"