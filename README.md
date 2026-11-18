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

配置分两处:`config.yaml`(模板 `config.yaml.example`)放这台机器长期的值,`.env` 留给敏感值与部署侧覆盖;同一个键环境变量 > config.yaml > .env。运行期参数(注册策略、核验通道、OIDC、配额等)在控制台「设置」页改,改完即生效。

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

## 部署

推一个 `v*` tag 只是发布制品；**真正切到目标机由目标机自己取**：目标机上有个 timer
每分钟看一眼 `:stable` 的 digest，变了就跑 `remote-deploy.sh`——拉镜像、切流、
验 `/api/health`，不过就按 `.deploy-before.env` 回滚。

方向是目标机出站。以前是构建侧 SSH 进来，目标机的防火墙（或云厂商的主机安全）把
构建节点当成可疑来源时，整条路会断在 `Connection refused`；现在没有任何入站连接。

### 发布一个版本

1. `git tag v0.1.2 && git push cnb v0.1.2` —— 构建并推 `v0.1.2` 与 `v0.1.2-web`，不动 stable
2. 仓库页面给这个 tag 点「部署到 dogfood」——流水线只做一件事：把 `:stable` 与
   `:stable-web` 指过去（`.cnb.yml` 的 `tag_deploy.dogfood`）
3. 目标机一分钟内自己切过去

**回滚** = 给上一个 tag 再点一次部署，stable 指回去，同样一分钟内生效。

### 目标机准备（一次性）

一台能跑 Docker + Compose 的 Linux 机器（腾讯内网机器也行）。仓库里的编排是
[deploy/docker-compose.deploy.yml](deploy/docker-compose.deploy.yml)，首次在上面执行：

```bash
sudo mkdir -p /opt/gwei/deploy && sudo chown "$USER" /opt/gwei
cd /opt/gwei
# 把仓库里的 deploy/docker-compose.deploy.yml 放到 /opt/gwei/deploy/，
# deploy/ci/remote-deploy.sh 放到 /opt/gwei/deploy/remote-deploy.sh
# 写 .env.prod(chmod 600):POSTGRES_PASSWORD / API_TOKENS / HARNESS_TOKEN /
#   CNB_REGISTRY / CNB_REGISTRY_USER / CNB_REGISTRY_TOKEN —— 拉制品库镜像用
# 其余 LLM_* / *_WEBHOOK_* 等按运行时参考配置，详见 .env.prod.example。
sudo install -m 755 deploy/ci/gwei-watch-deploy /usr/local/bin/gwei-watch-deploy
sudo install -m 644 deploy/ci/gwei-watch-deploy.service /etc/systemd/system/
sudo install -m 644 deploy/ci/gwei-watch-deploy.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now gwei-watch-deploy.timer
```

状态在 `/var/lib/gwei-deploy/`：`state` 记已部署的 digest，`deploy.log` 是切换日志。
同一个版本失败后 30 分钟内不重试，避免每分钟撞一次坏镜像。

轮询 15 秒一次。想让它「点完按钮就开始」而不等下一轮，再装一个本机触发口：

```bash
sudo install -m 755 deploy/ci/gwei-deploy-hook /usr/local/bin/gwei-deploy-hook
sudo install -m 644 deploy/ci/gwei-deploy-hook.service /etc/systemd/system/
sudo systemctl enable --now gwei-deploy-hook
# Caddy 里给站点加一条路由（`caddy validate` 后再 reload）：
#   handle /_deploy {
#       reverse_proxy 127.0.0.1:8099
#   }
```

`.cnb.yml` 的部署作业最后一步会 `POST /_deploy`，同步等结果：部署失败这枚作业跟着变红。
触发口不收版本号（接受哪一版由 `:stable` 决定），只做 3 秒限频；放一个
`/etc/gwei/deploy-hook.secret` 就变成要 `X-Gwei-Token`。轮询保留作兜底。

制品库凭据：CNB 个人设置里建一个只读令牌（`registry-package:read`），填进
`.env.prod` 的 `CNB_REGISTRY_TOKEN`，用户名固定 `cnb`。

## 发布制品

推一个 `v*` tag 就是一次发布:[.cnb.yml](.cnb.yml) 的 `tag_push` 把两个镜像构建出来推进制品的库,
tag 名与 `latest` 各打一份。拉取地址(`<org>/<repo>` 全小写):

| 镜像 | 拉取地址 |
|------|----------|
| engine | `docker.cnb.cool/<org>/<repo>:<tag>` |
| web | `docker.cnb.cool/<org>/<repo>:<tag>-web` |

两个镜像在同一个制品库仓库里,靠 tag 后缀区分。制品库按仓库授写权:另开一个
`<repo>-web` 仓库会拿到 `requested access to the resource is denied`。

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
