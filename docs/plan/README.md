# 平台 v2 重构总纲(租户原语 · 插件系统 v2 · 前端门控)

> 状态:已批准的总纲,后续每个 Phase 进入各自的 plan→implement 循环,子计划以
> `docs/plan/phase-X-*.md` 命名并在完成后打勾归档。
> 架构依据:[docs/platform-architecture.md](../platform-architecture.md)(三层协议 / 单前端 /
> 租户切分 / 插件 v2 三机制),本总纲覆盖其 §5 落地顺序的第 1-4 步。

## 0. 范围与不做清单

**本轮三个 Phase**:

- Phase A 租户原语(先行——事件与落库载荷从第一天带租户,避免插件层落地后再改一遍载荷契约)
- Phase B 插件系统 v2(本轮主诉焦点)
- Phase C 前端单应用模式门控(收尾卫生)

**明确不做**(留给后续轮次):Slot/UI 扩展协议、计费插件、gRPC 插件 server 实现
(v2 Registry 预留进程模型,但只实现进程内插件)、scheduler 循环(Observer 的 60s
trigger 只登记不调度)、`apps/selfhost` 目录更名、installation→tenant 真实映射
(多 GitHub App installation 支持另立轮次)。

**依赖顺序**:A → B → C(A 的租户字段是 B 的事件载荷契约的一部分;C 独立但最小,
放最后作为卫生清理)。

---

## Phase A 租户原语

目标:数据模型与执行链路具备租户维度;selfhost = 单租户(N=1)默认档,代码路径与
未来 SaaS 唯一。

### A1. 数据模型与迁移

- [ ] 新增 `engine/db/models/tenant.py`:`Tenant`(id UUID pk / slug str unique /
      name str / settings JSON / created_at TIMESTAMPTZ)。
- [ ] `models/__init__.py` 导出 Tenant。
- [ ] `project.py`:`tenant_id` FK → tenants.id,nullable=False。
- [ ] 迁移 `engine/migrations/versions/004_tenants.py`:
  - 建 `tenants` 表;
  - `projects.github_id` 现为**全局唯一** → 调整为 `(tenant_id, github_id)` 复合唯一
    (否则两个租户无法安装同一仓库);迁移需先删旧唯一约束/索引再建新的;
  - seed 默认租户(slug="default"),存量 projects 挂到默认租户。
- [ ] `config.py` Settings 增 `default_tenant_slug: str = "default"`。

### A2. 租户上下文:显式参数贯穿

> 论证:DBOS 的 workflow/step 可能在跨线程 executor 上重放执行,contextvar 不可靠;
> 租户 ID 必须是载荷的显式字段。

- [ ] `engine/api/routes/webhook.py` `_extract_payload`:payload 增加 `tenant_slug`
      (v1 恒取 `settings.default_tenant_slug`;预留注释:installation→tenant 映射点)。
- [ ] `engine/workflows/pipeline.py` `_persist_triage_impl`:按
      `(tenant_id, github_id)` upsert Project;Issue 创建携带租户关联(经 project)。
- [ ] `engine/shared/cache.py`:去重与缓存键统一携带租户前缀
      (`gwei:{tenant}:webhook-dedup:{delivery_id}` / `gwei:{tenant}:llm-analysis:...`)。
- [ ] 事件载荷(Phase B 事件总线消费方)顶层含 `tenant_id`——契约写进 B 的 manifest 说明。

### A3. DBOS 队列分区(公平性执行点)

- [ ] `app.py`:`register_queue_async(..., partition_concurrency=4)`(替代
      worker_concurrency,实测语义后定参)。
- [ ] `webhook.py` `_enqueue_workflow`:enqueue 携带
      `partition_key=payload["tenant_slug"]`(**风险项**:DBOS partitioned queue 要求
      每次 enqueue 必带 partition_key,且分区队列不支持 deduplication——幂等仍由
      `SetWorkflowID` 承担;子计划实现时先用 55432 临时库实测入队/恢复行为再接线)。

### A4. 验收标准与测试

- [ ] 单测:tenant 模型/迁移降级(up/down);payload 含 tenant_slug;
      (tenant, github_id) 复合唯一生效。
- [ ] 端到端(复用 `GWEI_TEST_DATABASE_URL` 门控模式):webhook → workflow → 落库
      带租户;重启恢复不变。
- [ ] dogfood 冒烟:55432 临时环境全链路复跑,检查 `projects.tenant_id` 与 dbos
      队列分区字段。
- [ ] 既有测试全绿;`dbos.workflow_status` 中无无分区的工作流。

---

## Phase B 插件系统 v2

目标:真实插件发现/注册替换硬编码 import;类型化事件总线跑通既有编排链;
Hook 管线与能力覆盖就位。红线:平台执行点(租户隔离/认证/配额/DBOS 持久化语义)
不设 hook 点——以代码结构保证(hooks 模块不暴露这些位置的接线函数)。

### B1. 模块布局与清理

- [ ] 新增 `engine/plugin_manager/manifest.py` — Manifest 解析与校验。
- [ ] 新增 `engine/plugin_manager/registry.py` — 发现/实例化/索引/生命周期。
- [ ] 新增 `engine/plugin_manager/events.py` — 进程内事件总线。
- [ ] 新增 `engine/plugin_manager/hooks.py` — Hook 管线。
- [ ] **删除** `engine/plugin_manager/dispatcher.py`(死代码:全仓库无调用方)。
- [ ] `__init__.py` 导出更新:PluginRegistry, EventBus, HookPipeline, Manifest +
      既有 PluginBase/PluginInfo/PluginType。

### B2. Manifest v2 与 proto 增量

- [ ] 读现有 8 份 `plugins/builtin/**/plugin.yaml`(sensor/fixer/diagnoser/... 均已
      存在 name/version/type/description/triggers/capabilities),扩展字段:
      ```yaml
      hooks:
        offered:   []                     # 本插件发布的扩展点
        subscribe: [{point: ..., mode: observe|transform|veto,
                     priority: 10, failure_mode: fail_open|fail_closed}]
      capabilities_priority: {}           # 能力名 -> 覆盖优先级(缺省 0)
      ```
- [ ] `base.py` PluginInfo 增量扩展(带默认值,旧构造全部兼容):`hooks_offered` /
      `hooks_subscribed` / `cap_priority` dict。
- [ ] `proto/plugin.proto` 增量:TriggerInfo 增 hooks 字段(wire-compatible,新增
      field number,不动既有);**manifest 与 proto 双写同步的风险由"清单为准,proto
      后续生成"策略缓解,子计划中注明**。
- [ ] 发现路径:builtin `plugins/builtin/{adapters,agents,actions}/*/*/{plugin.yaml}`
      + 环境变量 `PLUGINS_EXTRA_DIRS`(冒号分隔,外部插件目录——闭源插件的挂载点,
      本轮仅支持目录发现,进程内加载仍限 Python;gRPC 加载器后续轮次)。

### B3. Registry

- [ ] 目录扫描 → yaml 解析(校验 name/type 必填,重复 name 报错)→ 定位插件模块
      (builtin 目录名含连字符,沿用 importlib;约定:`<dir>/plugin.py` 内类名 =
      yaml name 转帕斯卡 + 后缀 Agent/Adapter/Action,与现有类名核对)→ 实例化。
- [ ] 三索引:`event_subscriptions`(event → [plugin])、`capabilities`
      (capability → [plugin],按 cap_priority 择优)、`hooks`(point → 排序订阅者)。
- [ ] 生命周期:`launch()`(逐插件 on_startup,失败隔离记 metrics 不中断)、
      `shutdown()`、`health_check_all()`。
- [ ] `runtime.py` 委托 registry:`get_adapter`/`get_sensor` 签名不变(查
      registry.capabilities/名字索引),webhook 与既有 36 测试零改动通过。

### B4. EventBus(进程内)

- [ ] `events.py`:`publish(event, payload)` fan-out 到订阅者;**best-effort 语义**
      (持久化与重试仍归 DBOS 工作流,总线不做投递保证——在模块 docstring 写明)。
- [ ] per-subscriber `asyncio.wait_for` 超时(默认 10s)+ 异常隔离(单订阅者失败
      不影响其他);`GweiMetrics` 计数 `plugin_events_published_total` /
      `plugin_event_handler_errors_total{plugin}`。
- [ ] 事件名沿用智能体既有声明:`issue.created/edited`、`sensor.processed`、
      `issue.labeled`、`diagnosis.complete`、`fix.generated`、`patch.approved`、
      `pr.created`、`review.completed`、`workflow.completed`、`pr.merged`。
      **载荷契约**:顶层 `tenant_id` + 领域数据。

### B5. HookPipeline

- [ ] `hooks.py`:`run(point, payload, mode)` — 按优先级排序执行订阅者;
      observe(结果丢弃)/ transform(链式修改载荷)/ veto(返回 False 即终止并审计:
      metrics `plugin_hook_veto_total{plugin,point}` + WARNING 日志含载荷摘要)。
- [ ] fail_open(订阅者异常 → 跳过继续)/ fail_closed(异常 → 按 veto 处理);
      默认 fail_open,veto 订阅者建议 fail_closed。
- [ ] 首批扩展点(数量克制,选真实接线处):`comment.posting`、
      `patch.generated`、`issue.triaged`(其余事件名已存在,不重复设点)。
- [ ] **不设**平台执行点 hook(见 Phase B 红线)。

### B6. 接线与保守事件链(已确认)

- [ ] `app.py` lifespan:`registry.discover() → registry.launch()`(DBOS launch 前)。
- [ ] `pipeline.py` fixer 步骤:改经能力通道
      `registry.execute_capability("patch.generate", params)`,保留直连
      `FixerAgent` fallback 参数供既有单测(文档注明 fallback 是测试过渡,后续移除)。
- [ ] `issue_triage_workflow`:persist 成功后
      `events.publish("sensor.processed", {tenant_id, issue: {...}})`。
- [ ] diagnoser 经 manifest 订阅 `sensor.processed` 自动触发;**已知并接受**:
      webhook issue 不携带 code 字段,其 `handle_event` 产出空诊断(函数列表为空),
      诊断结果仅记日志与 metrics,不影响 triage 工作流结果。fixer/deployer/reporter
      仍仅由 fix_suggestion_workflow(@gwei)触发——产品行为不变。
- [ ] 修复 `plugins/builtin/agents/*/plugin.py` 的 `sys.path.insert` hack:
      registry 加载时注入包路径,插件改用正常的 `engine.plugin_manager.base` 导入
      (一次清理到位,否则外部目录插件无法复用同一加载逻辑)。

### B7. 验收标准与测试

- [ ] 新增 `tests/test_integration/test_plugin_registry.py`:yaml 发现与解析、
      重复 name 拒绝、事件/能力/hook 三索引正确性、生命周期错误隔离、
      capabilities 择优覆盖。
- [ ] 新增 `tests/test_integration/test_event_bus.py`:fan-out、超时隔离、
      异常隔离、metrics 计数。
- [ ] 新增 `tests/test_integration/test_hooks.py`:三档语义、priority 排序、
      fail_open/fail_closed、veto 审计。
- [ ] triage 集成测试:发布 `sensor.processed` 后 diagnoser(以 spy 替身注册)
      收到含 `tenant_id` 的载荷。
- [ ] 既有 36 测试全绿;dogfood 冒烟复跑(55432)全链路 SUCCESS,
      日志出现 diagnoser 的空诊断记录。

---

## Phase C 前端单应用模式门控

目标:单一 Nuxt 应用按 `deployment_mode` 门控 SaaS 路由/菜单;顺带清理尸体。
依据:`apps/selfhost` 已通过 Nuxt layers `extends: ['@gwei/core']` 共享,
`@gwei/core` 层(nuxt.config/composables/api/mock/types)完全不动。

### C1. 模式开关

- [ ] `nuxt.config.ts`:runtimeConfig.public 增
      `mode: process.env.NUXT_PUBLIC_DEPLOYMENT_MODE || 'selfhost'`。
- [ ] `layouts/default.vue`:navItems 增加 `modes: ['saas']` 标注;渲染时按
      当前 mode 过滤(selfhost 档隐藏 SaaS 专属入口);页脚"Acme Corp 专业版"
      假租户卡片改为按 mode 显示(saas)/隐藏(selfhost)。
- [ ] 路由门控:`pages/login.vue`、后续 saas 专属页面统一约定
      `definePageMeta({ modes: ['saas'] })` + 一个全局 route middleware
      (`middleware/mode.ts`,非目标 mode 时 redirect 到 /dashboard)。

### C2. 卫生清理

- [ ] 删除 `dashboard/` 目录(仅剩 node_modules 尸体)。
- [ ] 删除根 `frontend/package.json` 的 `dev:saas`/`build:saas` 死脚本
      (指向不存在的 `@gwei/saas`)。
- [ ] README 移除过时的 "### dashboard/ - Next.js 前端项目" 小节。

### C3. 验收

- [ ] `pnpm build:selfhost` 通过;dev 起服务后 selfhost 档导航无 SaaS 项、
      直接访问受控路由被重定向;
- [ ] `NUXT_PUBLIC_DEPLOYMENT_MODE=saas` 时 saas 菜单可见(无认证后端,仅验证
      门控本身);
- [ ] 前端未引入新依赖;compose 引用(`pnpm dev:selfhost`、镜像名)不变。

---

## 里程碑与子计划对应

| Phase | 子计划文档 | 状态 |
|---|---|---|
| A 租户原语 | [phase-a-tenancy.md](phase-a-tenancy.md) | **已完成**(`0e39f98`..`513050b`);Spike 结论已回写子计划:分区队列 keyless 入队会静默 ENQUEUED,partition key 必须在唯一入队点设置;issues 约束扩展为 (project_id, github_id) |
| B 插件系统 v2 | `docs/plan/phase-b-plugins.md` | 待撰写 |
| C 前端门控 | `docs/plan/phase-c-frontend.md` | 待撰写 |

每份子计划完成后在本表打勾并附实施 commit 区间;Phase 间发现的新事实回写本总纲
(例如 A3 的 DBOS 分区实测结论)。

## 风险表

| 风险 | 缓解 |
|---|---|
| DBOS 分区队列 enqueue 语义(partition_key 必带、不支持 deduplication) | A3 实现前用临时库实测;幂等继续由 SetWorkflowID 承担 |
| (tenant_id, github_id) 复合唯一迁移对存量库的约束调整 | 迁移脚本显式 drop 旧约束再建新;up/down 测试 |
| manifest(yaml)与 proto 双写漂移 | 以 manifest 为准,proto 字段本轮仅增量声明,后续由清单生成 |
| runtime 兼容层与既有测试耦合 | get_adapter/get_sensor 签名冻结;registry 未启动时回退旧单例行为 |
| plugins `sys.path.insert` hack 清理牵动 7 个智能体导入 | B6 一次性替换,加载器注入路径;每个插件独立可 import 的测试覆盖 |
| diagnoser 空诊断噪音 | 仅日志+metrics,不落业务表;后续接 code 来源时自然消失 |
