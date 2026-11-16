# 插件系统 v2 参考

> 状态:现行 | 日期:2026-11-16
> 读者:插件作者、后端
> 上游:[平台架构](../explanation/platform-architecture.md)

插件与平台之间只有一份声明式合同:`plugin.yaml`。本文按「清单字段 → 注册表 → 事件总线 → Hook → UI → 运行时接线」的顺序说明当前实现。

## 清单字段

必填字段:name、version、type、description,以及 `class_name`(进程内插件)或 `endpoint`(进程外插件)中的一个,两个都给会被拒。

清单是唯一声明源。插件代码里没有 `info()`:名称、能力、订阅只在清单里声明一次。

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
    - slot: issue-board.bento
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
| `class_name` | 进程内插件:`plugin.py` 中要实例化的类名 |
| `endpoint` | 进程外插件:`host:port`;写了它就不导入任何代码,见[进程外插件](#进程外grpc插件) |
| `binding` / `tenant` | 实例服务哪个下游目标 / 哪个租户。进程内插件通常用实例属性声明;进程外插件没有实例属性可读,只能落在这里 |
| `triggers` | `type: event` 的 `events` 进入事件索引;`type: schedule` 在启动时装进 DBOS 调度器,见[周期巡检](#周期巡检) |
| `capabilities` | 本插件提供的能力名 |
| `tasks` | 能力名 → `execute_task` 任务名;缺省为能力名下划线形式 |
| `capabilities_priority` | 同名能力的覆盖优先级,高者优先 |
| `hooks.offered` | 本插件发布的扩展点(声明用途) |
| `hooks.subscribe` | 扩展点订阅;mode/priority/failure_mode/handler 见 Hook 一节 |
| `scopes` | 插件要的配置块(scope 名 → `prefix` / `required` / `optional`),见[配置(Scope)](#配置scope) |
| `effects` | 能力的效果声明,见[效果声明](#效果声明) |
| `ui.widgets` | 声明式卡片;slot 为插槽名,kind 为 metric 或 list,span 为 1–4 |
| `ui.pages` | iframe 页面;entry 缺省 index.html,禁止绝对路径、`..` 与反斜杠 |
| `effects` | 效果声明:execute / undo / window / verify,核心加载期校验 |
| `default_enabled` | 部署未显式选择时是否加载;false 表示备选项 |

## 注册表

- **发现路径**:`plugins/builtin/{adapters,agents,actions}/<plugin>/plugin.yaml`(两级),以及环境变量 `PLUGINS_EXTRA_DIRS`(冒号分隔)下的 `<pkg>/plugin.yaml`(单级,根会加入 `sys.path`)。
- **装插件不必重建镜像**:把外部插件放进挂载目录(生产编排里是 `/plugins-extra`),再 `POST /api/plugins/rescan` 即可。镜像内的 `plugins/` 是内置插件,外挂的是部署自己加的。
- **发现与启用是两件事**:发现只读清单,记进 `available()`;启用的才 import、注册、进索引。`states()` 列出包括未启用在内的全部插件。
- **当前的接入范围**:默认启用的来源适配器只有 GitHub(issue 与 PR)。GitLab、CNB 与 Alertmanager 随包提供但 `default_enabled: false`,是预留位;要用时打开清单里的开关或加进 `PLUGINS_ENABLED`。哪些插件默认开合以各清单为准,本文不维护第二份名单。
- **导入**:模块名为 `plugins.builtin.<category>.<dir>.plugin` 或 `<pkg>.plugin`;类名来自 `class_name`。
- **隔离**:单个插件的清单解析、导入、实例化失败只跳过自身,计 `plugin_discovery_errors_total`;同名插件重复注册直接报错。
- **多实例**:`register(manifest, instance, key=...)` 支持同一清单挂多个实例(每租户 / 每目标一个),实例键默认取清单名;同名清单内容不一致、实例键重复都直接报错。索引里存的是实例键。
- **启停的决定从哪来**:运行期显式决定(控制台写入,落在 `plugin-enablement` scope)> `PLUGINS_ENABLED` 白名单 > `PLUGINS_DISABLED` > 清单 `default_enabled`(缺省 true)。运行期决定压过环境变量,启停决定因此在重启后仍然生效。白名单里写了没人认领的名字会点名告警。
- **注册是原子的**:同名清单冲突、实例键重复、`effects` 里的能力没列进 `capabilities`,全部在任何写入之前判掉,注册失败不留痕迹。
- **三索引**:事件 → 插件列表;能力 → 提供者(按 priority 排序);Hook 扩展点 → 订阅者(按 priority 排序,索引里存的是订阅声明本身,同一插件对同一扩展点的多条订阅各保留各的 mode)。
- **生命周期**:`launch()` 逐个调用 `on_startup`,失败隔离;`shutdown()` 逆序;`health_check_all()` 汇总。
- **能力调用**:`registry.run_capability(capability, params)` 选优先级最高的提供者,按 `tasks` 映射任务名;无提供者抛 `LookupError`。
- **按目标解析**:传 `tenant=` / `binding=` 时改走 `registry.resolve()`,只做精确匹配,不跨目标回退;实例以 `tenant` / `binding` 属性声明自己服务谁,控制面能力用空值解析。诊断用 `registry.capability_bindings(capability)`。
- **按来源取适配器**:`engine/ingest/source.py` 的 `source_adapter(source)` 是核心与"有哪些来源"的唯一接触面;取不到一律抛 `LookupError`,不返回默认实现。`engine/shared/runtime.py` 的 `get_adapter(source)` 只是它的转调。
- **没有直连兜底**:`get_sensor()` / `get_fixer()` 只查注册表。注册表还没跑过发现、或部署未启用目标插件,都抛 `LookupError`,调用方如实报告未执行感知或修复。
- **Webhook 来源**:`registry.webhook_adapter(source)` 按实例的 `source` 属性选适配器;该实例必须声明 `webhook.receive`。来源重复直接报错。

## 运行期启停

发现之后,启停不用重启进程:

| 操作 | 做什么 | 端点 |
| --- | --- | --- |
| 打开 | 导入 + 实例化 + 注册 + `on_startup` | `POST /api/plugins/{name}/enable` |
| 关掉 | `on_shutdown` + 从事件/能力/效果/Hook 四个索引里摘掉 | `POST /api/plugins/{name}/disable` |
| 重扫目录 | 新出现的按决定启用,磁盘上没了的停用,已加载且没变的不动 | `POST /api/plugins/rescan` |

- 权限是 `plugins.write`;`GET /api/plugins` 与 `plugins.read`。
- 决定写进 `plugin-enablement` scope(`键=插件名`,`值=on/off`),启动时装回。写库失败只告警:开关已经生效,差别只是活不过重启。
- 摘索引是四个索引一起摘,停用后它不再被解析到。
- `GET /api/plugins` 列出包括未启用在内的全部插件,`enabled` / `instances` / `reason` 说明它此刻的状态与原因。
- `GET /api/plugins/widgets` 只取已启用插件的卡片。

## 进程外 gRPC 插件

插件跑在自己的进程里(自己的依赖、自己的语言),核心只持有一个代理。**声明仍旧在清单里**:

```yaml
name: remote-scan
version: 0.1.0
type: agent
description: 进程外扫描插件
endpoint: 10.0.0.5:50051
binding: prod               # 实例属性无从读取,服务哪个目标只能声明在这里
capabilities: [scan.dependencies]
tasks:
  scan.dependencies: scan   # 任务名映射照旧由核心解释
```

- **同一条注册路径**:发现流程见到 `endpoint` 就建代理,不走 `import`。之后的事件、能力解析、Hook、周期与进程内插件一字不差。
- **wire 只承载调用**:`proto/plugin.proto` 的 `PluginService` 覆盖 Startup / Shutdown / HealthCheck / Configure / HandleEvent / ExecuteTask / HandleHook。效果不开新 rpc:execute / undo / window / verify 都走 `ExecuteTask`,靠 `metadata["phase"]` 分阶段。
- **连接方向是核心 → 插件**。插件进程监听端口,核心按清单的 `endpoint` 连过去;没有"插件连回控制面注册"的反向连接——插件是什么由清单声明,核心不需要在运行时被通知一遍。
- **载荷是 JSON**,`bytes` 字段里放 UTF-8 的 JSON;返回值同样。
- **失败隔离**:连不上、超时、远端抛错、远端返回非 JSON,一律在 `GrpcPluginProxy` 里翻成 `GrpcPluginError`,调用方收到的是本插件的失败。grpc 的异常类型不泄漏给工作流。
- **超时**:`PLUGINS_GRPC_TIMEOUT_S`(默认 10 秒)统一收口;`health_check` 与 `on_shutdown` 用 2 秒。
- **握手不阻塞启动**:`on_startup` 连不上只记日志,`health_check()` 会让它在页面上显示为不健康。
- **桩生成**:`python scripts/gen_grpc_stubs.py`,生成物在 `engine/plugin_manager/grpc_proto/`,提交进仓库(运行时不依赖 protoc)。`--check` 用来抓"改了 proto 没重生成"。
- **写服务端**:用 `engine/plugin_manager/grpc_server.py` 的 `serve(plugin)`,只实现 `execute_task` / `handle_event` / `handle_hook` / `configure`,协议细节它兜住。

### 效果四方法:与进程内提供者同名同语义

声明了 `effects` 的进程外插件照样当效果提供者。四个阶段靠 `metadata["phase"]` 区分,任务名来自清单 `effects` 块:

| phase | 远端收到的 `task` | `params` | 期望返回 |
| --- | --- | --- | --- |
| `execute` | `effects.<cap>.execute.task` | 效果参数 | `{"handle": "...", ...}` |
| `undo` | `effects.<cap>.undo.task` | `{"args": {...}, "handle": "..."}` | 任意 dict |
| `window` | 能力名 | `{"effect": {...}, "handle": null}` | `{"seconds": n}` / `{"unbounded": true}` / `{"source": "..."}` |
| `verify` | 能力名 | `{"effect": {...}, "handle": "..."}` | `{"ok": bool, "facts": {...}}` |

插件写了 `execute` / `undo` / `window` / `verify` 四个方法时,`grpc_server` 直接交给它们,入参与进程内提供者一样(`window` / `verify` 收到的 `effect` 就是 `engine.change_unit.Effect`):从进程内迁到进程外,这四个方法一行都不用改。没写就退回 `execute_task(task, params)`,`params` 里带着 `phase` / `effect` / `handle`,自己分派。

- **句柄是不透明字符串**:远端在 `execute` 的返回值里给,核心原样存进账本、再原样带回来,从不解开它。远端可以拿它当自增 id、文件名或签过名的令牌。
- **`window` 报不出可撤性就不能自动执行**:只报 `source` 而不报 `seconds` / `unbounded` 等于"读不到窗口",单元按不可逆处理,与进程内提供者一致。
- **失败性质由远端声明**:`TaskResponse.error_kind = "not_applied"` 表示"确定没碰到下游",核心据此把单元记成 `failed`(可照原样重试);其它值或不填一律 `unknown`(要人去核)。远端抛 `engine.change_unit.EffectNotApplied` 时,`grpc_server` 自动翻成 `not_applied`。

### 配置下发

进程外插件读不到核心的环境变量与业务库,`config.get_scope_config()` 在插件进程里什么都不返回。所以配置是**推**下去的,不是插件来取的(连接方向只有核心 → 插件):

```yaml
scopes:
  adapter-acme:
    prefix: ACME_
    required: [token]
    optional: [base_url]
```

- 声明登记进配置表:控制台的设置页因此列得出字段,`validate_scope` 说得出缺哪一项(报的是要补的环境变量名)。同名 scope 已在代码里注册过时不覆盖——代码里的声明带模型与字段说明,比清单里的粗声明更准。
- 推的时机:插件 `on_startup` 成功之后、以及人改完配置(`PUT` / `DELETE /api/settings/scopes/{scope}`)之后。改配置不用重启。
- 一次推一个 scope 的**全量**值,不做增量:增量会让"删掉一个键"与"键未改"在插件侧长得一样。空值不下发。
- 插件实现 `configure(scope, values, missing)` 收下即可;它抛错就是拒收,核心把失败写进 `GET /api/plugins` 的 `error`(写成"配置没推下去:…"),不让它跟"启动失败"混在一起——插件在跑,差别只是它手里是旧配置。
- 没实现 `configure` 就不推:进程内插件自己读得到配置表,再送一份只是两份会漂移的事实。
- **示例**:`deploy/grpc-plugin-demo/`(`server.py` + `plugin.yaml` + 说明),e2e 用例在 `tests/test_integration/test_grpc_plugins.py`。
- `PLUGINS_GRPC="name=host:port,..."` 是给"临时接一个不在插件目录里的插件"用的兜底:该接法拿不到清单,也就没有任何能力,只能用来确认对面在不在。

## 周期巡检

清单里的 `type: schedule` 触发声明「到点跑哪个能力」,平台负责把它装进 DBOS 的调度器:

```yaml
capabilities: [scan.dependencies]
triggers:
  - type: schedule
    every: 6h                  # 必须整除分钟 / 小时 / 天
    capability: scan.dependencies
```

- **周期写成 `every`,不收 cron**。cron 读不出「多久一次」,也读不出「会不会漏」;换成秒数是平台的事。时长支持 `s` / `m` / `h` / `d` 与纯秒数,必须整除所在档位:不整除的「每 45 分钟」在任何按整点对齐的调度器上都会走成 45 → 15 → 45。写错的在发现阶段就被拒,计入 `plugin_discovery_errors_total`。
- **能力必须同时列在 `capabilities` 里**,与效果声明同一条规矩。
- **调度与幂等都由 DBOS 承担**:工作流 id 是 `sched-<调度名>-<点火时刻>`,重启后同一周期不会补跑。平台不自建循环。
- **启动时对账**:每条周期单独装上(一条写坏不拖累其余);清单里已经没人声明的周期按前缀清理,不让一个退役的巡检继续每六小时跑一次。
- **巡检结果是一个信号**,来源 `scan`;空结果表示本次巡检无命中,不产生事故。形状不对(缺 `subject` / `title`)当场抛出,记成失败的巡检——写坏的巡检记为失败,不当作无异常。

## 事件总线

`events.publish(event, payload)` 是进程内 fan-out,**best-effort**:

- 不持久化、不重试;需要可靠执行的事件链由 DBOS 工作流负责;
- 单个订阅者 10 秒超时,超时或异常只影响自身;
- 指标:`plugin_events_published_total{event}`、`plugin_event_handler_errors_total{plugin,kind}`。
- 现状:核心与内置插件都不 publish 事件,也没有内置订阅者;总线作为插件扩展面保留。

## Hook 管线

`hooks.apply(point, payload)` 按优先级执行订阅者,返回 `{"allowed": bool, "payload": ...}`:

- `observe`:只读旁听,返回值丢弃;
- `transform`:链式修改载荷,上一个输出是下一个输入;
- `veto`:返回假值即短路,`allowed=False`;
- `fail_open`:handler 异常跳过,管线继续;`fail_closed`:异常按 veto 处理;
- veto 审计:`plugin_hook_veto_total{plugin,point}` + WARNING 日志(载荷摘要);
- 默认 handler 名为 `handle_hook`,基类提供恒等实现。

当前调用点与返回值的使用方式:

| 扩展点 | 在哪 | 返回值怎么用 |
| --- | --- | --- |
| `comment.posting` | 应用效果前 | transform 改评论正文;veto 让 `comment.create` 候选记 `vetoed` |
| `patch.generated` | 补丁生成后 | transform 换掉补丁列表 |
| `issue.triaged` | triage 落库后、提议意图前 | transform 换掉 `analysis`;veto 让本次投递不再提议 |

**调用方必须使用返回的 payload**,继续用原始入参会让订阅者的修改失效。

红线:租户隔离、认证、配额执行、DBOS 持久化语义不设 Hook 点。

## UI 插槽与 iframe 页面

- **槽位是核心声明的清单**([slots.py](../../engine/plugin_manager/slots.py)):`issue-board.bento`(首页议题板的卡片列)、`issue-detail.sidebar`(议题详情右栏)、`settings.plugins`(设置页底部)。插件在清单里写了别的槽位,加载期直接拒绝。
- **widgets**:核心前端按 schema 渲染,插件不注入代码;当前 kind 为 metric / list,variant 为 default / green / yellow / red。页面侧统一用 `<PluginSlot slot="...">` 渲染,拉不到卡片时留一句提示,不把页面撑成空白。
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

回显规则写在字段上,用 pydantic 模型声明最省事 —— 字段、必填、能不能见,一处说清:

```python
from pydantic import BaseModel, Field

class GitHubAppSettings(BaseModel):
    app_id: str = Field(..., json_schema_extra={"expose": "always"})
    private_key: str = Field(..., json_schema_extra={"expose": "never"})
    owner_token: str = Field("", json_schema_extra={"expose": "always", "read_scope": "operate"})

config.register_model_scope("adapter-github-app", GitHubAppSettings, prefix="GITHUB_APP_")
```

- 命名:scope 为 `{类型}-{平台}-{功能}`,字段名 snake_case;环境变量为 `{PREFIX}{FIELD_NAME}`。
- 取值按序:`Settings` 里有同名字段就用它 → 进程环境变量 → `.env`。**插件声明的字段不需要先写进 `Settings`**,声明了就是可配的——声明了却读不出来,等于没这套机制。
- 缺项在启动时以 warning 点名(写的就是要设的环境变量名):声明了却没人填,比没声明更糟——沉默会拖到第一次真要调下游时才爆。
- **值可以存进业务库**:`PUT /api/settings/scopes/{scope}` 写一次,重启不丢,改完立即生效。库里存的值排在 `Settings` 与环境变量之前,页面上的修改不会被部署环境变量覆盖。
- **回显由字段自己声明**:`expose` 取 `never`(默认)、`masked`(给出 `sk-a…3456` 形式的掩码)、`always`;`read_scope` 取 `read`(默认)或 `operate`(只有运维令牌看得到值)。未声明的字段不返回。
- **`multiline: true`** 表示值里带换行(私钥、证书):控制台会换成多行输入,单行输入在粘贴时会把换行吃掉。字段的 `description` 同时用作输入框提示和校验失败时的那句"该填什么"。
- 用模型声明时,写入前顺手做形状校验:类型不对拒(422),"还没填全"不算错,缺什么由 `missing` 单独报。
- **值按租户分开**:`plugin_settings` 的主键是 `(tenant, scope, key)`。读的时候公共值打底、租户值覆盖;写的时候写进调用方令牌声明的租户。取值的接口都多一个 `tenant` 参数,不传就是只用公共值。
- 删除按租户生效:删掉租户覆盖值,读的时候落回公共值而不是落空。要彻底去掉公共值,用运维通配令牌删。
- `plugin_settings` 的表结构变过一次(加了 `tenant` 列),仓库没有迁移工具:`ensure_schema` 是 checkfirst,老库要先 `DROP TABLE plugin_settings;` 让它重建。
- 必填缺失由插件在 `on_startup` 自行决定:抛错、降级或忽略,核心不强制。
- **进程外插件在清单 `scopes` 块里声明**同一组事实,核心登记之后把值推下去(见[配置下发](#配置下发))。
- 封装配置类是可选的;插件也可以直接读 `config.settings`。
- 现有使用者:`plugins/builtin/adapters/github-app/`、`plugins/builtin/adapters/alertmanager/`。

## Webhook 适配器

Webhook 的字段名、事件名与验签方式都属于来源,不属于核心。一个来源 = 一个适配器插件:

- 实例属性 `source` 是来源名(`github` / `gitlab` / `cnb`),`binding` 是它的下游目标;
- 清单声明 `webhook.receive`,注册表按来源找它(`registry.webhook_adapter(source)`);同一来源有两个提供者直接报错,不猜;
- 适配器实现三个方法:`webhook_configured()`(密钥配没配)、`verify_webhook(headers, body)`(验签)、`parse_webhook(headers, body)`(投递 → 归一化事件);
- 实例属性 `mentions` 是**来源上人叫平台的触发词**:评论里没出现其中任何一个就不入队。`@gwei` 是 GitHub 适配器声明的,CNB 上是 `@CodeBuddy`;空元组 = 来源不接评论触发。核心不认识任何具体触发词;
- 归一化事件只有一种说法,定义在 [engine/ingest/events.py](../../engine/ingest/events.py):`kind`(issue / comment / merge / ping)、`source`、`repo`、`number`、`merge_sha` 等。核心不认识任何一家的原始字段;
- 入口只有一个:`POST /webhook/{source}`。新增来源不加路由分支:装上适配器,投递就有地方去;没装则回 503,不回落到"默认适配器"——把 GitLab 的投递交给 GitHub,比拒绝更糟。
- 适配器声明 `produces`:`event`(默认,产 issue / comment / merge 这类事件)或 `signal`(产信号,直接进事故管线)。产信号的适配器实现 `parse_signals(headers, body) -> list[signal]`,入口按 `ref + occurrence` 逐条去重后入队;一条重复不拖累其余。内置的 [alertmanager 适配器](../../plugins/builtin/adapters/alertmanager/plugin.yaml)就是 signal 型,接 Caddy、云雀、Grafana 也照 alertmanager 适配器的形状写,核心一行不改。
- `config_hint` 是适配器告诉人"该去填哪个环境变量"的一个字符串;没配密钥时入口按它回 503,核心不维护来源清单。

当前内置:`github-app`(issues / issue_comment / pull_request,`comment.create` + `pr.open`)、`cnb`(议题 / 评论 / 合并请求,`comment.create` + `pr.open`)、`gitlab`(仅合并请求)。GitHub 来源只有一个适配器:声明 `webhook.receive` 却拿不出 `source` 的插件会被 `source_adapter()` 跳过——装上了但接不上,比没有更费解。GitLab 还没补回评与开 MR 的能力,所以不声明、也不接评论触发 —— 声明了却调不通的效果比不声明更糟。

## 效果声明

`effects` 块声明插件能改什么、怎么撤、怎么验,由核心在加载期解析并校验,坏的直接拒绝注册。

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
- `window.read` 声明读取来源,真窗口在运行期读出来。读出来有三种答案:有到期时间、凭旧状态存在(不设到期)、算不出到期(按次数或容量淘汰)。前两种照常可撤;只有"完全读不到"才按不可逆处理。
- 每条 verify 必须是 `{query, expect}`。
- `execute.args` 是参数名清单,核心保留下来当 intent 提供者的菜单(见 [变更单元契约](../explanation/change-unit-contract.md)):点一个没声明过的能力,后台只会把它记成阻断。
- 声明的能力必须同时列在 `capabilities` 里,否则注册即报错。
- 同名效果由多个插件声明时,`capabilities_priority` 高者优先;并列直接报错,不按注册顺序猜。

效果提供者实现 `execute` / `undo` / `window` / `verify` 四个方法;声明的解释权在核心(`registry.effect_decl`)。进程外插件同样实现这四个方法,协议层负责把阶段分派过去,见[效果四方法](#效果四方法与进程内提供者同名同语义);不实现也能用,`execute_task` 会收到带 `phase` 的 `params`。

适配器还负责代码从哪来,三件事各有各的方法:

| 方法 | 谁在用 | 拿不到时 |
| --- | --- | --- |
| `workspace_source(repo) -> harness.workspace.Source` | 交给 harness 之前把代码铺进工作区 | 抛错,本次运行如实报告"没开工" |
| `read_pull(repo, number)` | 话题上已有 PR 时接着改它(要分支与地址) | 抛错,当成"没有 PR" |
| `mentions` | 评论里算不算叫了平台 | 空 = 不接评论触发 |

`Source` 是 `archive_url` / `token` / `branch` 三样:一个能下整棵树的归档地址(不走 git 协议——有些网络里 `github.com` 连不上,API 还在)、一份只在平台这一侧用一次的凭证、一条基线分支。代码由**这条投递的来源**给:CNB 的议题进来,工作区里就是 CNB 的仓库,不会拿 GitHub App 去拉一个同名仓库。它不是能力、不进出口菜单,容器永远拿不到凭证。

`execute` 抛什么,决定失败怎么记账:认得出没碰到下游(构造请求就失败、下游明确拒绝 4xx)时抛 `engine.change_unit.EffectNotApplied`,单元记 `failed`(可重试);抛别的异常一律记 `unknown`(请求可能已经到了对面,要人去核)。分不清失败原因时抛普通异常记 `unknown`,不要记成可重试的 `failed`。

## 插件就是 MCP 的工具来源

没有单独的 MCP 插件清单:插件声明过的效果自动成为 MCP 工具,名字以 `.read` 结尾的能力自动成为只读工具。核心只做翻译 —— `tool_specs(registry)` 原是给沙箱里的 agent 看的出口清单,`/mcp` 的 `tools/list` 用的是同一份。

想给外面的 agent 加一个工具,加能力,不要加接口:例如内置插件 [`platform-mcp`](../../plugins/builtin/actions/platform-mcp/plugin.yaml) 声明 `changes.read` / `incidents.read` / `topic.read`,装上之后任何 MCP 客户端的工具清单里就多了这三样,查的是本机的账本与事故。

清单只有一份,但**看到什么取决于凭据**:`tools/list` 在 `tool_specs` 之上按调用方的权限筛一遍,效果要 `changes.execute`,只读能力要 `changes.read`(见[运行时参考](runtime.md#工具按凭据暴露))。所以加能力时不用声明"它属哪个权限":

- 改世界的效果天然落在 `changes.execute` 下 —— 它本来就只能通过出口走闸门;
- `*.read` 结尾的能力天然落在 `changes.read` 下;
- 真要一把单独的权限(例如 `secrets.read`),在 `engine/auth/keys.py` 的 `CAPABILITY_PERMISSIONS` 里点名,再往 `engine/auth/__init__.py` 的 `PERMISSIONS` 里加一条。

资源检查在这里:工具能作用在哪些下游目标,由提供者实例自己声明的 `binding` 决定(`registry.tool_bindings`)。插件不需要另写资源清单——实例挂在哪,它的能力就在哪;同一能力在 `local` 与 `remote` 上各有一个实例,资源和工具清单里就有两个目标。密钥上勾了哪些资源,就只看得见对应目标上的工具。只读能力通常声明不出目标,资源检查对它不适用。

只读能力拿到的是平台按身份定下的租户,忽略调用方写在参数里的值,防止越权。

界面右下角的[控制台助手](runtime.md#控制台助手)用同一份清单:按会话身份筛一遍,再由会话白名单收窄。给助手加能力就是加能力,不是加接口。

## 运行时接线

- `app.py` lifespan:装回持久化的启停决定 → `registry.discover()` → 接进程外插件 → `registry.launch()`,失败隔离;
- triage:persist 成功后 `hooks.apply("issue.triaged")`,再经 `intent.propose` 与效果单元回评;扩展点的 transform 结果真的进后面的步骤;
- `@gwei` 评论:配了 `HARNESS_COMMAND` 就直接交给 harness(先开事故、再跑、再收口),没配才走补丁建议路径;
- `incident.handle` 是"整场交给 agent"的接缝:有提供者时告警工作流先走它,没有才回落到 `intent.propose` + 应用效果。循环写在插件里([operator](../../plugins/builtin/agents/operator/plugin.py)),平台只提供出口:改世界的能力每次落一个变更单元,只读能力(`.read` 结尾)不落账。跑在进程外沙箱里的 harness 不经过这个接缝,它直接调[出口端点](runtime.md);
- `intent.propose` 有两个内置提供者:`intent-builder`(规则,默认)与 `intent-llm`(模型,优先级 -1,要用得自己调上来)。提供者声明 `wants_history = True` 时,工作流会额外给它该租户最近的账本结论;没人声明的部署不为查询付账本成本。模型拿不准就给空 effects,空效果是合法结论;
- fix:`patch.generated` transform → `comment.posting` veto 检查;补丁生成经 `registry.run_capability("patch.generate")`,无提供者时**不产出补丁**并点名日志(不回退直连——回退直连会让 PLUGINS_DISABLED=sensor-agent,fixer-agent 失效);
- 事件与 Hook 调用放在 DBOS step 内,恢复重放不重复执行。

## 测试

- `tests/test_integration/test_plugin_system.py`:清单解析、发现隔离、三索引、能力择优、事件 fan-out、Hook 三档。
- `tests/test_integration/test_plugin_api.py`:插件 API、widgets、页面资产与路径穿越防护。
- `tests/test_integration/test_capability_resolution.py`:按 (租户, 目标) 解析、不跨目标回退、同一清单多实例。
- `tests/test_integration/test_intent_llm.py`:模型提供者的正常路径、各类降级(不编)、菜单剔除、履历进提示词与 evidence。
- `tests/test_integration/test_plugin_enablement_runtime.py`:运行期启停改真实行为、未启用的插件也列得出来、决定活过重启、白名单写错点名、内置插件声明的能力真的调得通。
- `tests/test_integration/test_grpc_plugins.py`:真起一个 gRPC 服务端,覆盖能力解析、Hook 往返、超时隔离、连不上时的行为,以及 `deploy/grpc-plugin-demo` 的端到端跑通。
- `tests/test_integration/test_grpc_effect_provider.py`:进程外插件当效果提供者——四方法与进程内一致、句柄往返、两种失败分得开、verify 不过照样回滚、示例插件跑完一条完整单元。
- `tests/test_integration/test_grpc_plugin_config.py`:清单声明的 scope 进配置表、启动后与改配置后推送、只推相关插件、拒收与缺项都说得出、没实现 `configure` 就不推。