# AGENTS.md

> 给编码 agent 的项目说明。人类入口见 [README.md](README.md)。
> 最后核对:2026-11-02,依据 `engine/`、`frontend/`、`plugins/` 与 `docs/`。

## 元规则:本文件自己怎么演进

| # | 规则 | 判据 |
| --- | --- | --- |
| M1 | 加规则必须先经维护者同意 | 在对话里提出、说明不加会出什么错,批准后才写 |
| M2 | 只加「不加就不知道」的规则;写稳定的抽象概念,不写易变细节 | 能从代码/工具/常识推出的不写;会随实现漂移的不写 |
| M3 | 规则必须可判 | 有明确判据;能被机检更好,但脚本不是必修项,更不要因此加门禁 |
| M4 | 同一规则只写一处,其余留指针 | 复制会漂移 |
| M5 | 规则失效就删,不保留历史 | 不写「历史上曾要求…」 |

> M3 是「有判据」,不是「必须写脚本/门禁」。能被结构强制的(类型、schema、测试、沙箱、权限)才叫控制;靠自觉的只是文档。

## 1. 这个仓库是什么(30 秒)

GweiOps 是 AI 驱动的运维智能体平台:GitHub 事件进入引擎,经 DBOS 工作流调用插件,落库并回评;前端是单个 Nuxt 应用,按部署档位门控。

| 层 | 技术 | 关键路径 |
| --- | --- | --- |
| engine | Python / FastAPI / SQLAlchemy async / DBOS | `engine/api/app.py`、`engine/workflows/pipeline.py` |
| plugins | Python,manifest v2 | `engine/plugin_manager/`、`plugins/builtin/` |
| frontend | Nuxt 3 / Vue 3 | `frontend/apps/selfhost/`、`frontend/packages/core/` |
| contracts | gRPC | `proto/plugin.proto` |
| state | Postgres + pgvector、Redis | `engine/db/`、`engine/shared/cache.py` |

文档入口:[docs/README.md](docs/README.md)。

## 2. 代码与文档不一致时:不设优先级

**没有默认优先级。** 代码和文档都会错:代码可能是 bug、半成品或临时方案;文档可能过期,也可能只是没落地的设想。

| 问题 | 只能由谁回答 |
| --- | --- |
| 现在实际会怎样(行为、返回值、错误码、文件是否存在) | 代码与文件树;文档说会怎样不算 |
| 本来该怎样、为什么这样定 | 文档;代码里没有意图 |

「代码说 A、文档说 B」是实现与意图的偏差,是一个需要处理的事件,不是能自动判定的对错。处理顺序:

1. 判定方向:实现错 / 文档错 / 两者说的不是同一件事。
2. 按判定动手:实现错 → 改代码或先记 issue;文档错 → 当次改文档;不是同一件事 → 拆开措辞。
3. 不静默单方面改动。改动要在当次回复里说明「按 X 改了 Y,依据 Z」,把裁决权留给人。
4. 维护者明确要求「以代码为准」时,那是本次决定,写进提交说明,不升级为通用规则。

## 3. 现状

只写「存在哪些层」。哪件事做到哪一步、什么还没做,以 [路线图](docs/plan/roadmap.md) 为唯一归属;判断进度读代码与路线图,不要从这张表推断。

| 层 | 存在的东西 | 唯一的事实来源 |
| --- | --- | --- |
| engine | FastAPI + DBOS 工作流 + SQLAlchemy async | `engine/` |
| 租户 | tenant_id 贯穿载荷与落库,队列按 tenant 分区 | `engine/workflows/`、`engine/db/` |
| 插件 | manifest v2、注册表(多实例、按目标解析)、事件总线、Hook、能力通道 | [插件系统](docs/reference/plugin-system.md) |
| 变更单元 | 契约、推进器、JSONL 账本、docker compose 下游样例 | [变更单元契约](docs/explanation/change-unit-contract.md) |
| frontend | 单个 Nuxt 应用,按 deployment_mode 门控 | `frontend/` |
| 对外接口 | 控制台只读 API、webhook | [运行时参考](docs/reference/runtime.md) |

## 4. 常用命令

```bash
# 测试(仓库根)
python -m pytest tests/ -q

# 需要真实 Postgres 的门控测试
GWEI_TEST_DATABASE_URL=postgresql+psycopg://... pytest tests/ -q

# 引擎(需 Postgres;会启动 DBOS)
uvicorn engine.api.app:app --reload

# 前端
cd frontend && pnpm install && pnpm dev:selfhost

# 全栈(Docker)
docker compose up
```

## 5. 改代码后必须同步的文档

| 改了什么 | 同步到 |
| --- | --- |
| 插件清单/注册表/事件/Hook/UI 插槽 | `docs/reference/plugin-system.md` |
| 工作流/队列/租户/Redis/LLM 计量/部署模式 | `docs/reference/runtime.md` |
| API 端点 | `docs/reference/runtime.md` |
| 架构边界或决策 | `docs/explanation/` 对应文档 |
| 文档结构或导航 | `docs/README.md` |

## 6. 文档规则

1. 一份文档一个 H1;标题不跳级、不超过 `####`;代码围栏必须带语言。
2. 链接用相对路径,禁止盘符绝对路径。
3. 只写当前状态。不写变更日志、勘误、「以前是」、TODO 清单;历史交给 git。
4. 同一事实只写一处,其余放链接。
5. 不写无法从仓库验证的事实;必须保留时标【未核实】并写明缺什么依据。
6. 禁止占位内容——篇幅必须对应信息量。
7. 如果仓库已有能抓到真实问题的检查,改完跑它;没有就不要为了这条规则新建一个门禁。

## 7. 禁止事项

- 不静默单方面改代码或文档来「对齐」;先判定偏差方向并说明依据。
- 不加靠自觉执行的门禁或规则:不能被结构强制、且抓不到真问题的检查,不写、不接 CI。
- 不复制事实:第二个副本改成链接。
- 不写历史:勘误、变更日志、「以前是」、TODO 清单都不进文档。
- 不把凭据、真实主机名或私钥写进仓库;配置走环境变量或密钥仓库。
