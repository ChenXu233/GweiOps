# =============================================================================
# Gwei Frontend — 多阶段构建（Nuxt 3 SSR）
# =============================================================================
# Stage 1: Builder — 安装依赖 + 构建
FROM node:22-alpine AS builder

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /build

# 复制依赖清单（利用缓存层）
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
COPY packages/core/package.json ./packages/core/
COPY apps/selfhost/package.json ./apps/selfhost/

RUN pnpm install --frozen-lockfile

# 复制源码
COPY packages/core/ ./packages/core/
COPY apps/selfhost/ ./apps/selfhost/

# 构建 Nuxt 应用
RUN cd apps/selfhost && pnpm build

# =============================================================================
# Stage 2: Runtime — 只复制 .output 产物
FROM node:22-alpine AS runtime

WORKDIR /app

# 从 builder 复制 Nuxt 的 nitro 独立构建产物
COPY --from=builder /build/apps/selfhost/.output ./.output

EXPOSE 3000

ENV HOST=0.0.0.0 \
    PORT=3000 \
    NODE_ENV=production

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://localhost:3000/ || exit 1

CMD ["node", ".output/server/index.mjs"]