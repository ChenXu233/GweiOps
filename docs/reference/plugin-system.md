# 插件系统 v2 参考

> 状态:现行 | 日期:2026-11-02
> 读者:插件作者、后端
> 上游:[平台架构](../explanation/platform-architecture.md)

插件与平台之间只有一份声明式合同:`plugin.yaml`。本文按「清单字段 → 注册表 → 事件总线 → Hook → UI → 运行时接线」的顺序说明当前实现。

## 清单字段

必填字段:name、version、type、description、class_name。

```yaml
name: example-agent
version: 1.0.0
type: agent            # adapter | agent | action | dashboard_component
description: 示例插件
class_name: ExampleAgent
triggers:
  - type: event
    events: [issue.created]
capabilities: [issue.analyze]
tasks:
  issue.analyze: analyze_issue
capabilities_priority:
  issue.analyze: 10
hooks:
  offered: [comment.posting]
  subscribe:
    - point: comment.posting
      mode: observe            # observe | transform | veto
      priority: 10
      failure_mode: fail_open  # fail_open | fail_closed
      handler: handle_hook
ui:
  widgets:
    - slot: dashboard.bento
      kind: metric
      span: 2
      title: 示例指标
      metrics:
        - { label: 调用, value: 0, sub: 累计, variant: green }
  pages:
    - title: 示例页面
      entry: index.html
```

| 字段 | 语义 |
| --- | --- |
| `class_name` | `plugin.py` 中要实例化的类名 |
| `triggers` | `type: event` 的 `events` 进入事件索引;`type: schedule` 只登记,当前没有调度循环 |
| `capabilities` | 本插件提供的能力名 |
| `tasks` | 能力名 → `execute_task` 任务名;缺省为能力名下划线形式 |
| `capabilities_priority` | 同名能力的覆盖优先级,高者优先 |
| `hooks.offered` | 本插件发布的扩展点(声明用途) |
| `hooks.subscribe` | 扩展点订阅;mode/priority/failure_mode/handler 见 Hook 一节 |
| `ui.widgets` | 声明式卡片;slot 为插槽名,kind 为 metric 或 list,span 为 1–4 |
| `ui.pages` | iframe 页面;entry 缺省 index.html,禁止绝对路径、`..` 与反斜杠 |
| `effects` | 效果声明:execute / undo / window / verify,核心加载期校验 |
| `default_enabled` | 部署未显式选择时是否加载;false 表示备选项 |

## 注册表

- **发现路径**:`plugins/builtin/{adapters,agents,actions}/<plugin>/plugin.yaml`(两级),以及环境变量 `PLUGINS_EXTRA_DIRS`(冒号分隔)下的 `<pkg>/plugin.yaml`(单级,根会加入 `sys.path`)。
- **启用**:发现不等于加载。`PLUGINS_ENABLED`(逗号或冒号分隔)给定时按白名单加载;否则用 `PLUGINS_DISABLED` 排除;再退回清单里的 `default_enabled`(缺省 true)。未启用的插件不 import、不注册、不进索引。
- **导入**:模块名为 `plugins.builtin.<category>.<dir>.plugin` 或 `<pkg>.plugin`;类名来自 `class_name`。
- **隔离**:单个插件的清单解析、导入、实例化失败只跳过自身,计 `plugin_discovery_errors_total`;同名插件重复注册直接报错。
- **多实例**:`register(manifest, instance, key=...)` 支持同一清单挂多个实例(每租户 / 每目标一个),实例键默认取清单名;同名清单内容不一致、实例键重复都直接报错。索引里存的是实例键,不是清单名。
- **三索引**:事件 → 插件列表;能力 → 提供者(按 priority 排序);Hook 扩展点 → 订阅者(按 priority 排序)。
- **生命周期**:`launch()` 逐个调用 `on_startup`,失败隔离;`shutdown()` 逆序;`health_check_all()` 汇总。
- **能力调用**:`registry.run_capability(capability, params)` 选优先级最高的提供者,按 `tasks` 映射任务名;无提供者抛 `LookupError`。
- **按目标解析**:传 `tenant=` / `binding=` 时改走 `registry.resolve()`,只做精确匹配,不跨目标回退;实例以 `tenant` / `binding` 属性声明自己服务谁,控制面能力用空值解析。诊断用 `registry.capability_bindings(capability)`。
- **兼容入口**:`engine/shared/runtime.py` 的 `get_adapter()` / `get_sensor()` 先查注册表,注册表未加载时回退直连单例。

## 事件总线

`events.publish(event, payload)` 是进程内 fan-out,**best-effort**:

- 不持久化、不重试;需要可靠执行的事件链由 DBOS 工作流负责;
- 单个订阅者 10 秒超时,超时或异常只影响自身;
- 指标:`plugin_events_published_total{event}`、`plugin_event_handler_errors_total{plugin,kind}`。
- 现状:核心与内置插件都不发布事件,也没有内置订阅者。总线作为插件扩展面保留;若长期没有真实使用者,应当删除而不是留着当装饰。

## Hook 管线

`hooks.apply(point, payload)` 按优先级执行订阅者,返回 `{"allowed": bool, "payload": ...}`:

- `observe`:只读旁听,返回值丢弃;
- `transform`:链式修改载荷,上一个输出是下一个输入;
- `veto`:返回假值即短路,`allowed=False`;
- `fail_open`:handler 异常跳过,管线继续;`fail_closed`:异常按 veto 处理;
- veto 审计:`plugin_hook_veto_total{plugin,point}` + WARNING 日志(载荷摘要);
- 默认 handler 名为 `handle_hook`,基类提供恒等实现。

红线:租户隔离、认证、配额执行、DBOS 持久化语义不设 Hook 点。

## UI 插槽与 iframe 页面

- **widgets**:核心前端按 schema 渲染,插件不注入代码;当前 kind 为 metric / list,variant 为 default / green / yellow / red。
- **pages**:前端动态路由 `/plugins/<name>` 用 `<iframe sandbox="allow-scripts">` 加载;`GET /api/plugins/{name}/ui/{path}` 由 engine 提供资产,resolve 后必须仍在插件 ui 目录内。
- 相关端点:`GET /api/plugins`、`GET /api/plugins/widgets`、`GET /api/metrics`。

## 配置(Scope)

插件配置走 `engine/shared/config.py` 的 Scope:按环境变量前缀 + 必填/可选字段名注册一块配置,再按 scope 名取回 dict。

```python
from engine.shared.config import config

config.register_scope(
    name="adapter-github-app",
    prefix="GITHUB_APP_",
    required=["app_id", "private_key"],
    optional=["webhook_secret"],
)
scopes = config.get_scope_config("adapter-github-app")   # {"app_id": ..., ...}
missing = config.validate_scope("adapter-github-app")    # ["private_key"]
```

- 命名:scope 为 `{类型}-{平台}-{功能}`,字段名 snake_case;环境变量为 `{PREFIX}{FIELD_NAME}`。
- 必填缺失由插件在 `on_startup` 自行决定:抛错、降级或忽略,核心不强制。
- 封装配置类是可选的;插件也可以直接读 `config.settings`。
- 现有使用者:`plugins/builtin/adapters/github-app/`。

## 效果声明

`effects` 块声明「这个插件能改什么、怎么撤、怎么验」,由核心在加载期解析并校验,坏的直接拒绝注册。

```yaml
effects:
  comment.create:
    label: 在 Issue / PR 上发一条评论
    execute: { task: create_comment, args: [repo, issue_number, body] }
    undo: { task: delete_comment, kind: symmetric }
    window: { read: comment_present }
    verify:
      - { query: comment_exists, expect: "true" }
```

- `undo.kind`:`retained`(下游保留旧状态)或 `symmetric`(撤销作用在同一对象上)。
- `window.read` 是读取来源,不是时长;真窗口在运行期读出来,声明只说读什么。
- 每条 verify 必须是 `{query, expect}`。
- 声明的能力必须同时列在 `capabilities` 里,否则注册即报错。
- 同名效果由多个插件声明时,`capabilities_priority` 高者优先;并列直接报错,不按注册顺序猜。

插件只实现 `execute` / `undo` / `window` / `verify` 四个方法;声明的解释权在核心(`registry.effect_decl`)。

## 运行时接线

- `app.py` lifespan:`registry.discover() → registry.launch()`,失败隔离;
- triage:persist 成功后 `hooks.apply("issue.triaged")`,再经 `intent.propose` 与效果单元回评;
- fix:`patch.generated` transform → `comment.posting` veto 检查;补丁生成经 `registry.run_capability("patch.generate")`,无提供者时回退 `FixerAgent`;
- 事件与 Hook 调用放在 DBOS step 内,恢复重放不重复执行。

## 测试

- `tests/test_integration/test_plugin_system.py`:清单解析、发现隔离、三索引、能力择优、事件 fan-out、Hook 三档。
- `tests/test_integration/test_plugin_api.py`:插件 API、widgets、页面资产与路径穿越防护。
- `tests/test_integration/test_capability_resolution.py`:按 (租户, 目标) 解析、不跨目标回退、同一清单多实例。
