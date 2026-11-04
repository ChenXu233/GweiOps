# GweiOps 平台架构决策(SaaS · 前端 · 插件系统 v2)

> 状态:已决策(2026-09-12) | 前置讨论:对话式架构评审,证据见 git 提交 `c7ea1a9..ccb5ae0`
> 本文只记录已决事项;目标与硬约束见 [目标](goals.md)。

## 1. 开源边界:三层协议

| 层 | 位置 | 协议 | 内容 |
|---|---|---|---|
| 核心(本仓库) | `engine/` `frontend/` `plugins/builtin/` | **AGPL-3.0** | engine、前端(单应用,见 §2)、SaaS 控制面代码、内置开源插件 |
| 插件契约 | `proto/` | **MIT** | gRPC PluginService、事件/Hook/页面清单 schema——任何人可按契约写开源或闭源插件 |
| 官方增值插件 | 独立私有仓库(如 `gweiops-plugins-pro`) | **商业专有** | 计费、高级连接器等;经 SaaS 套餐或私有化授权交付 |

设计心智模型:**闭源的东西只准活在插件层**。核心负责"强制",插件负责"扩展与定价"。

约束与已知边界:
- AGPL 防止竞品"修改后闭源托管",**不防止**原样照抄托管;对应护城河 = 商标 + 增值插件 + 运营。
- 官方闭源插件不得放入本仓库;只经 gRPC 进程外边界接入(见 §5)。
- 待办:frontend 补 AGPL LICENSE 声明;核心团队立 CLA(保留未来企业模块专有化的权利)。

## 2. 单前端,模式分叉

不拆 `apps/saas` / `apps/selfhost`,**单一 Nuxt 应用**,按 `deployment_mode` 运行时门控:

- saas 档:登录/注册/租户/计费路由启用;
- selfhost 档:安装向导 + 本地管理员令牌;**selfhost = 单租户(N=1)且不装计费插件的运行档位**,代码路径与 SaaS 唯一。
- `apps/selfhost` 目录择机更名为 `apps/web`(涉及 compose/CI 镜像名,非紧急)。

## 3. 租户:原语进核心,经营面进插件

承重墙不能是插件——租户是所有数据访问与工作流的横切面前提,放进可卸载的扩展会形成
"插件注册表存于按租户隔离的库"的自举循环。

| 关注点 | 归属 |
|---|---|
| 租户上下文、数据隔离、认证中间件、DBOS 队列按租户分区 | 核心(开源) |
| 配额/公平性**执行机制**(DBOS `partition_concurrency` 等) | 核心 |
| 用量计量上报(`LLMCallResult.tokens_used` 等) | 核心(机制) |
| 订阅、计划、配额策略、账单、开通流程 | 计费插件(可闭源) |

核心强制、插件定价。selfhost 下计费插件缺省,租户原语取单租户默认值。

## 4. 插件系统 v2:为什么重构、重构什么

### 4.1 时机

现有 plugin_manager 只有 PluginBase 接口 + 无人调用的 PluginDispatcher,插件加载是
硬编码 import——**尚无生态锁定成本,契约改动接近零成本;这是唯一便宜的窗口**。
（决策时状态;现已由 registry/事件总线/Hook 落地,见 [插件系统参考](../reference/plugin-system.md)。）
此外,七个内置智能体的 `triggers` 已隐含完整事件编排链,只是没有引擎执行:

```text
issue.created → sensor ──sensor.processed→ diagnoser ──diagnosis.complete→ fixer
──fix.generated→ deployer ──patch.approved→ reporter ... workflow.completed → learner
```

v2 的本质:把这条潜在编排骨架升级为类型化、可治理的运行时。

### 4.2 三种受支持的变更机制(替代"直接修改")

**直接 monkey-patch 其他插件或核心代码是明确禁止的**。系统原生与插件行为的变更只能经:

1. **配置旋钮(Config Scopes)**——已有机制(RegisterScope/GetScopeConfig)。行为开关与参数,
   启动时读取;改动后需重启,核心没有热重载。
2. **Hook 管线**——在命名扩展点上按优先级执行订阅者,语义分三档:
   `observe`(只读)/ `transform`(修改载荷)/ `veto`(否决操作)。
   扩展点选自领域主干,首批 ~12 个:`webhook.received`、`issue.triaged`、`analysis.completed`、
   `patch.generated`、`comment.posting`、`comment.posted`、`pr.created`、`deploy.started/finished`、
   `workflow.completed`、`llm.call.before/after`(只读,供计量)。
   每个订阅者声明 `failure_mode`: `fail_open` / `fail_closed`,配 per-subscriber 超时与错误隔离;
   veto 必须留审计痕迹(dogfood 教训:不可观测的失败会被无声吞掉)。
3. **能力覆盖(Capability Override)**——同名能力按优先级竞争提供,注册表选最高优先级实现。
   用于"替换系统原生实现"(如商业插件替换内置 `issue.duplicate_detection`),是替换行为的唯一合法通道。

### 4.3 不可 Hook 的平台执行点

租户隔离、认证、配额执行、DBOS 持久化语义**不接受 transform/veto**。插件可 observe 策略决策,
不可绕过强制。插件页面/令牌按 capability 收窄。

### 4.4 前端扩展:Slot 模型

核心页面声明**扩展槽**(`dashboard.bento`、`issue-detail.sidebar`、`settings.plugins` …),
插件经清单注册:

- 简单配置 UI:**声明式 JSON schema**,核心渲染(零代码、安全);
- 复杂页面:**iframe 沙箱**,插件自持 Web 资源,经 engine 鉴权代理,任意语言/技术栈;
- 禁止向主应用 bundle 注入可执行代码。

清单(Manifest)统一承载全部声明,是闭源插件与外界唯一的合同:

```yaml
apiVersion: v2
kind: agent            # agent | adapter | action | service
triggers:  [...]       # 事件订阅(兼容现有 triggers 字段)
capabilities: [...]    # 提供/覆盖的能力
hooks:
  offered:    ["patch.riskassessed"]      # 本插件发布的扩展点
  subscribe:  [{point: patch.generated, mode: transform, priority: 10, failure_mode: fail_open}]
ui:
  pages:    [{route: k8s-scaler, title: 扩缩容策略, entry: iframe:/k8s-scaler/}]
  widgets:  [{slot: dashboard.bento, kind: schema, schema: widgets/risk-card.json}]
scopes: [...]          # 配置旋钮(沿用现有 Scope 规范)
```

### 4.5 进程模型

- 进程内 Python 插件:hook 链直接调用;
- gRPC 插件:异步分发、超时隔离、崩溃不影响核心(hook 链执行器为核心组件);
- 官方闭源插件一律走 gRPC;进程内 import 仅限本仓库 builtin 开源插件。

## 5. 落地顺序

未完成项见 [docs/plan/roadmap.md](../plan/roadmap.md);已完成的阶段不再在文档里保留清单:

1. 前端合并单应用 + `deployment_mode` 路由门控(小)——总纲 Phase C;
2. 核心租户原语:租户表 + 上下文注入 + 查询隔离 + 队列分区(中)——总纲 Phase A(**先于插件 v2 实施**,使事件/落库载荷从第一天带租户);
3. 插件系统 v2 骨架:真实插件发现/注册(替换硬编码 import)+ 事件总线跑通内置智能体既有编排链(中)——总纲 Phase B;
4. Hook 管线 + 能力覆盖 + Manifest v2(中)——总纲 Phase B;
5. Slot/UI 扩展协议 v1:声明式 schema + iframe(中);
6. 计费插件(闭源侧,消费 §3 的用量事件与 §5 的 UI 协议)。

## 6. 与既有文档的关系

- 目标与硬约束见 [目标](goals.md);本文不重复。
- 插件配置的落地形态见 [插件系统参考](../reference/plugin-system.md) 的「配置(Scope)」一节。
- 变更与回滚的合同见 [变更单元契约](change-unit-contract.md)。
