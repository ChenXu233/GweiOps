# 运行时参考

> 状态:现行 | 日期:2026-11-02
> 读者:后端、运维
> 口径:基于当前代码;阈值与 TTL 为代码常量,改动时同步本文。

## 服务与端口

| 服务 | 端口 | 说明 |
| --- | --- | --- |
| engine | 8000 | FastAPI;健康检查 `/api/health` |
| web | 3000 | Nuxt 3;开发时经 Nitro 同源代理 `/api/**` → engine |
| postgres | 5432 | pgvector/pgvector:pg16;业务表 + DBOS schema |
| redis | 6379 | 只承载可丢失的临时状态 |

## 工作流

| 工作流 | 触发 | 链路 |
| --- | --- | --- |
| `issue_triage_workflow` | issues opened/edited | Sensor 分析 → 落库 → `issue.triaged` Hook → `intent.propose` → 效果单元(回评,可撤销) |
| `fix_suggestion_workflow` | 评论含 `@gwei` | 落库 → 补丁建议 → `patch.generated` transform → `intent.propose` → 效果单元(回评,不自动建 PR) |

- 持久化:DBOS 状态在 Postgres 的 `dbos` schema;重启后未完成工作流从断点恢复。
- 队列:`gwei-agents`,`partition_concurrency=4`;入队必须带 `queue_partition_key=tenant_slug`(缺 key 会静默入队,幂等由 `SetWorkflowID` 兜底)。
- 事件与 Hook 调用放在 DBOS step 内,恢复重放不会重复执行。
- 效果执行以 `workflow_id:effects:effect:<n>` 为幂等键:重放只复用账本结论,不二次外呼。

## 变更账本

- 后端:`CHANGE_LEDGER_BACKEND`。`db`(默认)写业务库 `change_events` 表,启动时 checkfirst 建表;`file` 写 `CHANGE_LEDGER_PATH`(默认 `var/change-ledger.jsonl`)的单文件 JSONL,仅用于演示与离线调试——并发追加与租户隔离都靠不住。
- 一行一个事件,只追加、不改写。顺序看自增主键,不看时间戳(机器时钟会回拨)。
- 一个单元判定、执行、放行、撤销各写一行,`unit_id` 相同;当前状态取 id 最大的那行。
- 查询按 `tenant` 收窄(`GET /api/changes?tenant=`)。它是查询范围,不是鉴权:认证接进来之前不构成越权保护。
- 阻断的单元有两个出口,各写一行账:放行(`approve`)与否决(`veto`)。放行只表示"此刻有人在场",执行后照样读窗口、照样验证,真正不可逆的如实记成 `irreversible`。
- 撤销前置条件:最新行为已执行且有句柄;已撤销返回 409,未执行返回 400,提供者不可用返回 503。
- 放行前置条件:最新行为 `blocked`,否则 409。否决前置条件:最新行未执行,已执行的只能撤销。
- 幂等:同一 `idempotency_key` 重放只复用账本结论,不二次外呼。

## 租户

- webhook payload 顶层携带 `tenant_slug`;当前取 `settings.default_tenant_slug`(默认 `default`)。
- `projects` 唯一约束 `(tenant_id, github_id)`;`issues` 唯一约束 `(project_id, github_id)`。
- 每租户的凭据、队列分区、模型用量都按 `tenant_slug` 归属。

## Redis

- 只承载可丢失状态;Redis 故障时降级放行,不阻塞主链路。
- webhook 去重:`gwei:{tenant_slug}:webhook-dedup:{delivery_id}`,TTL 6 小时。
- LLM 分析缓存:内容哈希键(前缀 `gwei:`),TTL 24 小时;失败文案不写缓存。
- 幂等兜底始终是 DBOS workflow ID,不是 Redis。

## LLM 与计量

- `engine/llm/client.py` 经 LiteLLM 调用;重试 3 次,指数退避。
- 指标:`gwei_llm_calls_total{model}`、`gwei_llm_tokens_total{model}`、`gwei_llm_call_duration_seconds{model}`。
- AgentSession 的 state 记录 `llm_tokens`,作为计费聚合源。

## 部署模式

- 前端档位:`NUXT_PUBLIC_DEPLOYMENT_MODE`,取值 `selfhost`(默认)或 `saas`。
- 页面用 `definePageMeta({ modes: [...] })` 声明可见档位;`middleware/mode.global.ts` 对不匹配的路由重定向 `/dashboard`;布局按 `modes` 过滤导航。
- 后端 `Settings.deployment_mode` 默认 `saas`,与前端档位目前是两个独立字段,没有强制校验对齐。部署时分别设置。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/dashboard` | 面板聚合数据 |
| GET | `/api/dashboard/pending` | 待处理项 |
| GET | `/api/dashboard/overnight` | 夜间任务 |
| GET | `/api/dashboard/canary` | 金丝雀状态 |
| GET | `/api/issues`、`/api/issues/{id}` | Issue 列表 / 详情 |
| GET | `/api/repos` | 仓库列表 |
| GET | `/api/runs` | 执行记录(一次 AgentSession 一次执行,含起止与耗时) |
| GET | `/api/settings` | 设置(脱敏) |
| GET | `/api/plugins`、`/api/plugins/widgets` | 插件清单 / 插槽声明 |
| GET | `/api/metrics` | 指标快照 |
| GET | `/api/changes` | 变更账本当前状态(按单元折叠,可按 verdict / binding 过滤) |
| GET | `/api/changes/{id}` | 单个单元的全部事件(执行与撤销) |
| POST | `/api/changes/{id}/rollback` | 撤销已执行的单元,并追加一行审计 |
| POST | `/api/changes/{id}/approve` | 放行一个阻断的单元,执行后照样读窗口与验证 |
| POST | `/api/changes/{id}/veto` | 不做这次变更,追加一行否决 |
| GET | `/api/plugins/{name}/ui/{path}` | 插件 iframe 资产 |
| POST | `/webhook/github` | GitHub Webhook(issue 事件) |
| POST | `/webhook/github/comment` | GitHub 评论事件 |

## 插件

清单、注册表、事件总线、Hook、UI 插槽与配置见 [插件系统](plugin-system.md)。
