# GweiOps

> AI 驱动的全链路运维智能体平台

**GweiOps —— 摆渡未济，恒守既济。**

GweiOps 由 Python 引擎、Nuxt 3 前端、插件系统与 gRPC 契约组成。

```text
engine/     Python FastAPI 核心（工作流、插件、API、数据）
frontend/   Nuxt 3 单应用（selfhost / saas 两种部署档）
plugins/    插件（adapters / agents / actions）
proto/      gRPC 插件契约
docs/       文档（索引见 docs/README.md）
```

## 运行环境要求

| 依赖 | 版本要求 | 说明 |
|------|----------|------|
| Python | 3.12 | 运行 `engine/` 后端与测试 |
| Node.js | 22 | 运行 `frontend/` 前端 |
| pnpm | 10 | 前端包管理器 |
| PostgreSQL | 16 | 业务库，需安装 [pgvector](https://github.com/pgvector/pgvector) 扩展 |
| Redis | 7 | 临时状态缓存（webhook 去重、LLM 结果缓存） |

> 使用 Docker 方式启动时，上述依赖已包含在镜像与 compose 配置中，无需在宿主机单独安装。

## 快速开始

### Docker(开发)

```bash
docker compose up
# API:   http://localhost:8000/docs
# 前端:  http://localhost:3000
```

### Docker(生产)

```bash
cp .env.prod.example .env.prod
# 编辑 .env.prod,填入 POSTGRES_PASSWORD 等必填项
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 手动安装

```bash
# 后端(仓库根目录;uv 按 engine/uv.lock 装,避免同一份代码装出不同的依赖树)
cd engine && uv sync --extra dev && cd ..
uv run --project engine python .ci/engine-tests.py   # 契约、迁移、测试一起查
uv run --project engine uvicorn engine.api.app:app --reload

# 前端
cd frontend
pnpm install
pnpm dev:selfhost
```

## 部署 CI（dogfood）

`master` 上有发布制品，真正把服务切到服务器上靠一次手动部署：给 tag 在仓库页面点
「部署到 dogfood」（环境定义在 `.cnb/tag_deploy.yml`），触发 `.cnb.yml` 的
`tag_deploy.dogfood`。它拉制品库里该 tag 的两个镜像，在目标机上 `docker compose up`，
验 `/api/health` 不过就自动回滚到切换前的镜像。目标是“正确接入 dogfood 之前”的
初始自动化部署：tag 人工挑、脚本自动跑，不需要登录服务器敲命令。

### 目标机准备

一台能跑 Docker + Compose 的 Linux 机器（腾讯内网机器也行）。仓库里的编排是
[deploy/docker-compose.deploy.yml](deploy/docker-compose.deploy.yml)，首次在上面执行：

```bash
sudo mkdir -p /opt/gwei && sudo chown "$USER" /opt/gwei
cd /opt/gwei
# 把仓库里的 deploy/docker-compose.deploy.yml 放进来，再写 .env.prod（chmod 600）：
#   POSTGRES_PASSWORD / API_TOKENS —— 必填
#   CNB_REGISTRY / CNB_REGISTRY_USER / CNB_REGISTRY_TOKEN —— 拉制品库镜像用
# 其余 LLM_* / *_WEBHOOK_* 等按运行时参考配置，详见 .env.prod.example。
```

`.env.prod` 只在目标机上，不进仓库、不过流水线。CI 每次部署把本次镜像地址写回它的
`GWEI_ENGINE_IMAGE` / `GWEI_WEB_IMAGE`，切换前的镜像留在 `.deploy-before.env`。

### 密钥仓库

CNB 没有 `from_secret`，敏感值放密钥仓库，用 `imports` 注入。模板见
[deploy/ci/secret.example.yml](deploy/ci/secret.example.yml)。在密钥仓库（如
`ChenXu233/secrets`）的 Web 界面建一个 `gwei-deploy.yml`，把私钥、目标机地址填进去，
并保证文件里的 `allow_events` 含 `tag_deploy.*`，`.cnb.yml` 的 imports 路径指向它。

### 内网能不能访问

**默认连不进**：CNB SaaS 的构建节点在公网，腾讯内网服务器没有公网入站时，SSH 不通。
两条路都能走：

| 方式 | 怎么配 | 适合 |
| --- | --- | --- |
| 跳板机 | 密钥里给 `PROXY_HOST` / `PROXY_PORT` / `PROXY_USER` / `PROXY_KEY`，流水线经跳板机 SSH 进内网 | 已有 JumpServer / 跳板机，改动最小 |
| 自定义 Runner | 把一台能通内网、且能出网访问 CNB 站点的机器接成根组织构建节点，流水线加 `runner.namespace: group` + `runner.tags` | 长期、需要对内网多机部署 |

部署方向是「构建侧主动连目标机」，目标机不用开放公网端口。详见
[官方文档：自定义构建节点](https://docs.cnb.cool/zh/build/build-node.md)与
[企业版 VPC 互通](https://docs.cnb.cool/zh/enterprise.md)。

## 发布制品

推一个 `v*` tag 就是一次发布:[.cnb.yml](.cnb.yml) 的 `tag_push` 把两个镜像构建出来推进制品的库,
tag 名与 `latest` 各打一份。拉取地址(`<org>/<repo>` 全小写):

| 镜像 | 拉取地址 |
|------|----------|
| engine | `docker.cnb.cool/<org>/<repo>:<tag>` |
| web | `docker.cnb.cool/<org>/<repo>-web:<tag>` |

本机拉取先登录:

```bash
docker login docker.cnb.cool -u cnb -p <访问令牌>
```

镜像只按 tag 发布,`master` 上的每次提交不进制品库。GitHub 侧另有 `build.yml` 把同样的镜像推到
`ghcr.io/<org>/<repo>`(`-web` 后缀给前端)。

## 文档

从 [docs/README.md](docs/README.md) 进入。第一次建议按「平台架构 → 运行时参考 → 写插件」的顺序读。

## 许可证

本仓库以 [AGPL-3.0](LICENSE) 授权。
