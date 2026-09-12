# Phase A 子计划:租户原语

> 状态:已实施(`0e39f98` 子计划,`513050b` 实现) | 母本:[docs/plan/README.md](README.md) Phase A

相对总纲的三个细化决策(实施前已核实 API/Schema):

1. **issues.github_id 也有全局唯一问题**:001 迁移中 `issues.github_id` 同样是
   inline `unique=True`——两租户安装同一仓库时,issue 的 GitHub ID 在两租户下相同,
   会撞唯一约束。改为 `(project_id, github_id)` 复合唯一:project 隶属唯一租户,
   等价保证租户内唯一,且无需给 issues 加 tenant 冗余列。
2. **幂等键迁移到 EnqueueOptions**:dbos 2.31 的 `EnqueueOptions` 同时支持
   `workflow_id` 与 `queue_partition_key`,入队统一改走
   `DBOS.enqueue_workflow_with_options_async(queue, wf, options, payload)`,
   替代 `SetWorkflowID` 上下文(少一层隐式状态,且 options 是分区队列的必经之路)。
3. **租户解析时机**:webhook 保持零 DB 访问,payload 只带 `tenant_slug`;
   persist 步骤按 slug get-or-create Tenant(默认租户 "default" 常驻)。

## A0. Spike:DBOS 分区队列语义实测(先于一切接线)

55432 临时库上验证四件事,结论写入本节:

- [x] `register_queue_async(..., partition_concurrency=N)` 注册成功;
- [x] 带 `queue_partition_key` 的 enqueue 正常执行并出结果;
- [x] 分区队列**不带** partition_key 入队的实际行为(见结论 4:静默 ENQUEUED);
- [x] `workflow_id` 冲突时 options 路径的幂等行为(见结论 3、6)。

> Spike 结论(2026-09-12,dbos 2.31.1 实测):
>
> 1. `register_queue_async(..., partition_concurrency=N)` 注册分区队列正常;
> 2. **生产路径确认**:`with SetWorkflowID(id), SetEnqueueOptions(queue_partition_key=slug):
>    await DBOS.enqueue_workflow_async(q, wf, payload)` —— 三上下文嵌套可用,
>    执行与取结果正常(保留函数对象引用,不需要 name-based EnqueueOptions);
> 3. **幂等确认**:同 `workflow_id` 二次入队,系统库仅 1 行,不重复执行;
> 4. **无 key 入队的真实行为比文档更危险**:不报错,工作流行正常创建、状态永远
>    ENQUEUED、worker 永不认领——必须以代码约定保证每次入队都带
>    `SetEnqueueOptions`(实现中封装进 `_enqueue_workflow` 单点);
> 5. 不同 partition key 的工作流均正常执行;
> 6. 附带发现:name-based `EnqueueOptions` 路径要求**模块限定名**
>    (如 `engine.workflows.pipeline.issue_triage_workflow`),且系统库跨进程持久,
>    同 workflow_id 不同函数名会触发 `DBOSConflictingWorkflowError`。
>    本轮不采用该路径。

## A1. 模型与迁移

- [ ] `engine/db/models/tenant.py`:`Tenant(id UUID pk, slug str unique,
      name str, settings JSON, created_at TIMESTAMPTZ)`。
- [ ] `models/__init__.py` 导出 Tenant。
- [ ] `project.py`:加 `tenant_id` FK → tenants.id(不可空);去 `github_id`
      全局 unique;表参数 `__table_args__ = (UniqueConstraint("tenant_id", "github_id"),)`。
- [ ] `issue.py`:去 `github_id` 全局 unique;`__table_args__` 加
      `UniqueConstraint("project_id", "github_id")`。
- [ ] 迁移 `engine/migrations/versions/004_tenants.py`(down 可逆):
  1. 建 `tenants`;
  2. seed 默认租户(slug="default",固定 UUID 便于回滚);
  3. `projects` 加 `tenant_id` FK(nullable=False,先以默认租户回填存量行);
  4. drop `projects_github_id_key`、`issues_github_id_key`(001 inline unique
     的 Postgres 默认命名);
  5. 建复合唯一 `uq_projects_tenant_github`、`uq_issues_project_github`。
- [ ] `config.py`:`default_tenant_slug: str = "default"`。

## A2. 载荷与键

- [ ] `webhook.py _extract_payload`:payload 增 `tenant_slug`
      (v1 恒取 `config.settings.default_tenant_slug`;注释锚点:
      installation→tenant 映射在此处接入)。
- [ ] `webhook.py _enqueue_workflow`:改
      `enqueue_workflow_with_options_async(queue, wf, EnqueueOptions(
      workflow_id=f"{prefix}-{delivery_id}",
      queue_partition_key=payload["tenant_slug"]), payload)`;
      删除 SetWorkflowID 用法。
- [ ] `cache.py`:键带租户段。`dedup_once` 键由调用方拼
      `gwei:{slug}:webhook-dedup:{delivery_id}`;pipeline 的 llm-analysis 键
      `cache_key("llm-analysis", slug, title, body)`。
- [ ] `pipeline.py _persist_triage_impl`:开头按 slug get-or-create Tenant;
      Project upsert 条件改 `(tenant_id, github_id)`;AgentSession.state 增
      `tenant_id`。
- [ ] `app.py`:`register_queue_async(..., partition_concurrency=4)`。

## A3. 验收与测试

- [ ] 新增 `tests/test_integration/test_tenancy.py`:
  - payload 断言:`_extract_payload` 产出含 `tenant_slug`;
  - 缓存键:llm-analysis 键随租户不同而不同;
  - (门控)迁移 up/down + 复合唯一:同 github_id 不同租户可建两个 project,
    同租户同 github_id 被拒;issues 同理(经 project);
  - (门控)e2e:webhook → workflow → `projects.tenant_id` 落库;
- [ ] 既有 e2e(`test_pipeline.py TestWorkflowEndToEnd`)适配:fake session
  需多应答一次 Tenant 查询;pipeline fake 载荷加 `tenant_slug`。
- [ ] 全量回归全绿(不带 PG:全部通过含新单测;带 PG:含门控项)。
- [ ] dogfood 冒烟(55432/56379/18000):triage 全链路 SUCCESS,
  `projects.tenant_id` 非空,`dbos.workflow_status` 无报错,环境清理。

## A4. 收尾

- [ ] 总纲里程碑表 Phase A 标完成 + commit 区间;
- [ ] Spike 结论如引起设计变化,回写本文件与总纲风险表。

## 提交拆分

1. `docs(plan): phase-a tenancy sub-plan`
2. `feat(engine): tenancy primitives`(模型+迁移+接线+测试,含 spike 后的文档回写)
