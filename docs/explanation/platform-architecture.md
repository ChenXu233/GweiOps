# GweiOps 平台架构决策(SaaS · 前端 · 插件系统 v2)

> 状态:已决策(2026-11-13) | 前置讨论:对话式架构评审,证据见 git 提交 `c7ea1a9..ccb5ae0`
> 本文只记录已决事项;目标与硬约束见 [目标](goals.md)。

## 1. 授权:AGPL-3.0

engine、前端、内置插件与 `proto/` 契约均以 **AGPL-3.0** 授权。

任何人都可以把本代码原样或修改后对外提供服务。竞争壁垒落在运营、客户关系与商标上,不在授权条款里。

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
| 租户上下文、数据隔离、认证中间件、DBOS 队列按租户分区 | 核心 |
| 配额/公平性**执行机制**(DBOS `partition_concurrency` 等) | 核心 |
| 用量计量上报(`LLMCallResult.tokens_used` 等) | 核心(机制) |
| 订阅、计划、配额策略、账单、开通流程 | 计费插件 |

核心强制、插件定价。selfhost 下计费插件缺省,租户原语取单租户默认值。

## 4. 插件系统 v2:为什么重构、重构什么

### 4.1 时机

现有 plugin_manager 只有 PluginBase 接口 + 无人调用的 PluginDispatcher,插件加载是
硬编码 import——**尚无生态锁定成本,契约改动接近零成本;这是唯一便宜的窗口**。
（决策时状态;现已由 registry/事件总线/Hook 落地,见 [插件系统参考](../reference/plugin-system.md)。）
决策时曾认为七个内置智能体的 `triggers` 隐含一条完整事件编排链。这条链后来没有实现:依赖它的空壳插件已删除,推理侧改由 `intent.propose` 的提供者承担(见 [变更单元契约](change-unit-contract.md))。

v2 留下的真实骨架是:清单、注册表、能力通道、Hook、UI 插槽。

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
   用于"替换系统原生实现"(如外部插件替换内置 `issue.duplicate_detection`),是替换行为的唯一合法通道。

### 4.3 不可 Hook 的平台执行点

租户隔离、认证、配额执行、DBOS 持久化语义**不接受 transform/veto**。插件可 observe 策略决策,
不可绕过强制。插件页面/令牌按 capability 收窄。

### 4.4 前端扩展:Slot 模型

核心页面声明**扩展槽**(`issue-board.bento`、`issue-detail.sidebar`、`settings.plugins` …),
插件经清单注册:

- 简单配置 UI:**声明式 JSON schema**,核心渲染(零代码、安全);
- 复杂页面:**iframe 沙箱**,插件自持 Web 资源,经 engine 鉴权代理,任意语言/技术栈;
- 禁止向主应用 bundle 注入可执行代码。
- **槽位由核心持有**:当前是 `issue-board.bento`、`issue-detail.sidebar`、`settings.plugins` 三个。插件写了不存在的槽位,加载期就拒绝——槽位写错不该表现为"装了但页面上什么都没有"。
- **卡片的数字分两类**:平台指标由核心在请求时从收集器读(清单里写 `metric.name`);插件自己的业务数据走只读能力(`source: {capability, args}`,**提案**,未实现),渲染时回调一次。渲染路径上不许改世界。
- **取数的失败分两层,不混在一起**:
  - **加载期**:带 `source` 的卡片,能力名必须以 `.read` 结尾、且列在本插件自己的 `capabilities` 里,否则加载期就拒绝。所以**没装上的插件没有卡片**——不存在"插件不在、卡片还在"这种情形。
  - **渲染期**只剩两种:超时(默认 1 秒,可能下次就好)与报错(插件自己的问题)。两者都退回清单里声明的值,但卡片上说的话不同:「暂时取不到」与「取数失败」,各自计一次指标,不合并——超时是运气,报错是 bug,合成一个数就都看不出来了。
- **UI 声明不进 gRPC**。`proto` 里没有、也不该有 UI 消息:声明是静态合同,渲染不依赖插件进程存活。需要活连接的只有"取数"与"交互",它们走能力通道,而不是给每个插件维持一条 UI 长连接。

清单(Manifest)统一承载全部声明,是插件与平台之间唯一的合同:

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
  widgets:  [{slot: issue-board.bento, kind: schema, schema: widgets/risk-card.json}]
scopes: [...]          # 配置旋钮(沿用现有 Scope 规范)
```

### 4.5 进程模型

- 进程内 Python 插件:hook 链直接调用;
- gRPC 插件:异步分发、超时隔离、崩溃不影响核心(hook 链执行器为核心组件);
- 进程外插件一律走 gRPC;进程内 import 仅限本仓库 builtin 插件。
- **声明留在清单,不上 wire**。进程外插件与进程内插件共用同一份 `plugin.yaml`:控制台在进程没连上时也能说明它是什么,加载期就能校验,两边走同一条注册路径。wire 只承载调用。
- **wire 现在的缺口只有一处**:`proto` 有生命周期、Scope、事件、任务,但没有 hook 回调——进程外插件在清单里订阅了 hook,核心没有地方调它。效果不需要新的 rpc:`execute` / `undo` / `window` / `verify` 都是"任务名 + JSON 参数",`handle` 与窗口查询走参数。

### 4.6 投递入口:只对接,不自建

平台不复刻观测能力。证书快过期、容量不够、CVE 该修——这些判断由本来就在做这件事的系统给出(Caddy、云雀、Grafana、扫描器……);平台只负责把它们的投递接进来,变成同一种说法。自己实现一套探测,只会得到"两套告警各说各话"。

- **入口只有一个**:`POST /webhook/{source}`。核心不认识任何一家的字段、签名或令牌头;接一个新系统 = 一个声明 `webhook.receive` 的适配器插件,不加路由分支,不加来源白名单。
- **两种产出**:`event`(代码托管的 issue / comment / merge)与 `signal`(告警与巡检)。共用验签、去重与 503 口径,差别只在入队后走事故管线还是走三条工作流。
- **当前范围**:只接 GitHub 的 issue 与 PR。GitLab、CNB 与告警适配器是预留位(`default_enabled: false`),形状已定,打开开关即可用;适配器的写法见[写一个插件](../how-to/write-a-plugin.md#5-接一个来源webhook-适配器)。
- **拉取型来源用 DBOS 的调度器,不自建循环**:同一周期只跑一次由系统库里的工作流 id 保证,重启不补跑。

机制细节在[插件系统参考](../reference/plugin-system.md),这里只记边界与取舍。

## 5. 落地顺序

先后本身就是决策,记在这里;做到哪一步以[工作分解](../plan/wbs.md)与代码为准,本文不维护状态。

1. 前端合并单应用 + `deployment_mode` 路由门控;
2. 核心租户原语:租户表 + 上下文注入 + 查询隔离 + 队列分区(**先于插件 v2**,使事件与落库载荷从第一天带租户);
3. 插件系统 v2 骨架:真实插件发现/注册(替换硬编码 import)+ 事件总线;
4. Hook 管线 + 能力覆盖 + Manifest v2;
5. Slot/UI 扩展协议 v1:声明式 schema + 槽位 + iframe;
6. 计费插件(消费 §3 的用量事件与 §5 的 UI 协议)。

## 6. 与既有文档的关系

- 目标与硬约束见 [目标](goals.md);本文不重复。
- 插件配置的落地形态见 [插件系统参考](../reference/plugin-system.md) 的「配置(Scope)」一节。
- 变更与回滚的合同见 [变更单元契约](change-unit-contract.md)。