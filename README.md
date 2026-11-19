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

生产走全自动：推一个**正式版** `v*` tag 即发布制品并自动切到生产。切到目标机这一步
仍是目标机自己取——每套部署各有一个 timer 看自己的制品通道——生产看 `stable`，测试看
`test-stable`。digest 变了就跑 `remote-deploy.sh`——拉镜像、切流、验 `/api/health`，
不过就按 `.deploy-before.env` 回滚。方向是目标机出站，构建侧不连目标机，因此不需要
CNB 构建节点与生产机内网互通，也不用给动态出口 IP 加白名单。

### 正式版 tag 怎么判

`v` 开头且**不带连字符**算正式版（`v1.2.3`），带 `-` 的是预发布（`v1.2.3-rc1`、
`v1.2.3-beta.1`）。判定在流水线里按 tag 名做：预发布照常同步镜像仓、发制品，但不碰
`stable` 通道，不会误上生产。

### 发布一个版本

1. `git tag v1.2.3 && git push cnb v1.2.3` —— 正式版：构建并推 `v1.2.3` 与
   `v1.2.3-web`，自动把 `stable` 通道指过去，并打一下目标机触发口，立即切到生产
2. 推 `v1.2.3-rc1` 这类预发布 tag —— 只发制品，不动 `stable`，不上生产
3. 测试部署仍走页面：给任意 tag 点「部署到 test」，流水线把 `test-stable` 通道指过去
   （`.cnb.yml` 的 `tag_deploy.test`），再打目标机触发口

生产推送权限应收紧到 master/owner。若要「推 tag 后人工确认」的闸口，删掉 `.cnb.yml`
里的 `auto deploy stable on release tag` 作业，改为页面给 tag 点「部署到 dogfood」
（`.cnb.yml` 的 `tag_deploy.dogfood`）。轮询 15 秒一次只作兜底。

**回滚** = 给上一个正式版 tag 再点一次「部署到 dogfood」，通道指回去，立即生效。

### 构建侧要连目标机时（可选）

当前链路是目标机主动出站拉制品，不需要构建侧连生产机。若确实要从构建侧远程执行命令
（CNB SaaS 出口 IP 动态，不适合加白名单），官方给三条中转路子，选其一：

- **私有代理**：自有代理服务器路由请求，用代理的固定 IP 访问目标机。
- **SSH 跳板机**：`cnbcool/ssh` 插件的 `proxy_host` 系列参数经跳板机连内网机器，
  示例见 [JumpServer 用法](https://cnb.cool/cnb/plugins/cnbcool/ssh)。
- **腾讯云插件**：`tencentcom/tcloud-cmd` 借腾讯云自动化助手（TAT）远程执行命令，
  实例开通「自动化助手」并给 API 密钥授 CVM/TAT 权限即可，无需开放入站端口，
  见 [插件说明](https://cnb.cool/cnb/plugins/tencentcom/tcloud-cmd)。

这三样都不是纯内网直连；要真正的 CNB 与企业内网双向互通，需用部署到自有腾讯云 VPC
的企业版。凭据统一放密钥仓库用 imports 注入，不写进本仓库。

重建容器时前端有约 **20–30 秒的空窗**（compose 先删旧容器再起新的），这期间访问站点会看到 502。健康检查已覆盖前端（`/login`），所以「部署成功」意味着前端也已经就绪；空窗内的失败会触发回滚。

### 生产与测试分开

两套部署用不同的目录、compose project、端口和状态目录；凭据也各用一套，尤其
`CNB_WEBHOOK_TOKEN`、`CNB_TOKEN`、`API_TOKENS`、`HARNESS_TOKEN` 不要复用。

| 部署 | 通道 | 目录 | compose project | 端口 | 状态目录 |
| --- | --- | --- | --- | --- | --- |
| 生产 | `stable` | `/opt/gwei/prod` | `gwei-prod` | 8000 / 3000 | `/var/lib/gwei-deploy/prod` |
| 测试 | `test-stable` | `/opt/gwei/test` | `gwei-test` | 18000 / 13000 | `/var/lib/gwei-deploy/test` |

目标机上准备两套文件：

```bash
sudo mkdir -p /opt/gwei/prod/deploy /opt/gwei/test/deploy && sudo chown "$USER" /opt/gwei
# 每个目录各放一份 deploy/docker-compose.deploy.yml 与 deploy/ci/remote-deploy.sh，
# 再各写一份 .env.prod / .env.test(chmod 600)，详见 .env.prod.example。
# 生产 .env.prod: COMPOSE_PROJECT_NAME=gwei-prod / GWEI_CHANNEL=stable
# 测试 .env.test: COMPOSE_PROJECT_NAME=gwei-test / GWEI_CHANNEL=test-stable
#               GWEI_ENGINE_PORT=18000 / GWEI_WEB_PORT=13000
```

两个 watcher 单元只在变量上不同：

```ini
# /etc/systemd/system/gwei-watch-prod.service 追加
[Service]
Environment=GWEI_CHANNEL=stable
Environment=GWEI_PROJECT_DIR=/opt/gwei/prod
Environment=GWEI_COMPOSE_PROJECT=gwei-prod
Environment=GWEI_STATE_DIR=/var/lib/gwei-deploy/prod
Environment=GWEI_DEPLOY_SCRIPT=/opt/gwei/prod/deploy/remote-deploy.sh

# /etc/systemd/system/gwei-watch-test.service 追加
[Service]
Environment=GWEI_CHANNEL=test-stable
Environment=GWEI_PROJECT_DIR=/opt/gwei/test
Environment=GWEI_COMPOSE_PROJECT=gwei-test
Environment=GWEI_STATE_DIR=/var/lib/gwei-deploy/test
Environment=GWEI_DEPLOY_SCRIPT=/opt/gwei/test/deploy/remote-deploy.sh
```

然后启用两个 timer：

```bash
sudo cp deploy/ci/gwei-watch-deploy.timer /etc/systemd/system/gwei-watch-prod.timer
sudo cp deploy/ci/gwei-watch-deploy.timer /etc/systemd/system/gwei-watch-test.timer
# timer 里 Unit= 分别改成 gwei-watch-prod.service / gwei-watch-test.service
sudo systemctl daemon-reload
sudo systemctl enable --now gwei-watch-prod.timer gwei-watch-test.timer
```

状态在各自的 `GWEI_STATE_DIR`：`state` 记已部署的 digest，`deploy.log` 是切换日志。
同一个版本失败后 30 分钟内不重试，避免每分钟撞一次坏镜像。

想让「点完按钮就开始」而不等下一轮，装一个本机触发口。两个环境共用一个入口，
按 `X-Gwei-Channel` 选对应的 watcher 环境：

```bash
sudo install -m 755 deploy/ci/gwei-deploy-hook /usr/local/bin/gwei-deploy-hook
sudo install -m 644 deploy/ci/gwei-deploy-hook.service /etc/systemd/system/
# 按实际目录改 service 里的 GWEI_CHANNEL_* 变量，再启用：
sudo systemctl daemon-reload && sudo systemctl enable --now gwei-deploy-hook
# 每个环境的站点各加一条路由（`caddy validate` 后再 reload）：
# 生产域名：
#   handle /_deploy {
#       reverse_proxy 127.0.0.1:8099
#   }
# 测试域名同样加 /_deploy，反代到测试机的 127.0.0.1:8099
```

`.cnb.yml` 的部署作业最后一步会 `POST /_deploy` 并带上 `X-Gwei-Channel`，同步等结果：
部署失败这枚作业跟着变红。触发口不收版本号（接受哪一版由通道 digest 决定），只做
3 秒限频；放一个 `/etc/gwei/deploy-hook.secret` 就变成要 `X-Gwei-Token`。
`DEPLOY_HOOK_URL` 在 `.cnb.yml` 里有默认值（本机地址），不用额外配置；`DEPLOY_HOOK_TOKEN` 可选，配了要和服务器上的 `/etc/gwei/deploy-hook.secret` 一致。
轮询 15 秒一次作兜底。

制品库凭据：CNB 个人设置里建一个只读令牌（`registry-package:read`），填进
两套 env 的 `CNB_REGISTRY_TOKEN`，用户名固定 `cnb`。

### 让 NPC 用测试部署

NPC 跑在 CNB 流水线里，它进哪套部署取决于哪个 `/webhook/cnb` 收到投递。把测试部署的
`/webhook/cnb` 配到专用 webhook，`CNB_WEBHOOK_TOKEN` 用测试专用值，并在测试 env 里配：

```bash
SANDBOX=cnb
GWEI_SANDBOX_CNB_REPO=<你的仓库>
GWEI_SANDBOX_CNB_IMAGE=cnbcool/default-npc:latest
GWEI_SANDBOX_CNB_EVENT=api_trigger_harness
```

`CNB_TOKEN` 要有触发该仓库 `api_trigger` 的权限；回评、拉代码都走测试部署自己的令牌。
用 `@CodeBuddy` 触发一次，看评论落在哪个部署、账本写在哪套库即可确认。

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
