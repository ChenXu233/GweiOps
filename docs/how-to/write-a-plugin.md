# 写一个插件

> 状态:现行 | 日期:2026-11-14
> 读者:插件作者
> 上游:[插件系统参考](../reference/plugin-system.md)、[变更单元契约](../explanation/change-unit-contract.md)

插件与平台之间只有一份合同:`plugin.yaml`。本文按"能被加载 → 能接来源 → 能改世界 → 能被定时调用 → 会配置 → 怎么验"的顺序写;**字段的完整语义不在本文重复**,统一查[插件系统参考](../reference/plugin-system.md)。读之前先看一眼[平台架构](../explanation/platform-architecture.md)第 4 节:为什么直接改核心代码是被禁止的,以及三条合法的变更通道。

## 1 先选对形状

| 你要做的事 | 目录 | 关键声明 | 现成样板 |
| --- | --- | --- | --- |
| 把外部系统的投递接进来 | `adapters/` | `webhook.receive` + `source` | [github-app](../../plugins/builtin/adapters/github-app/plugin.yaml)、[alertmanager](../../plugins/builtin/adapters/alertmanager/plugin.yaml) |
| 提供一个能力(判断、生成、执行) | `agents/` `actions/` | `capabilities` + `tasks` | [sensor](../../plugins/builtin/agents/sensor/plugin.yaml)、[intent-llm](../../plugins/builtin/agents/intent-llm/plugin.yaml) |
| 一次可撤销的下游改动 | `actions/` | `effects` | [docker-compose](../../plugins/builtin/actions/docker-compose/plugin.yaml) |
| 到点自己跑一次 | 任意 | `triggers: type: schedule` | 暂无内置样板 |
| 在页面上加一块 | 任意 | `ui.widgets` / `ui.pages` | 见[第 9 节](#9-在页面上加一块) |

一个插件可以同时做几件事:GitHub 适配器既接投递,也声明 `comment.create` / `pr.open` 两个效果。

## 2 放哪里

内置插件放在仓库的 `plugins/builtin/` 下,一个插件一个目录;外部插件用 `PLUGINS_EXTRA_DIRS`(冒号分隔)指定根,根下每个 `<pkg>/plugin.yaml` 是一个插件。

```text
plugins/builtin/
  adapters/<plugin>/plugin.yaml + plugin.py
  agents/<plugin>/plugin.yaml + plugin.py
  actions/<plugin>/plugin.yaml + plugin.py
```

外部根不区分 `adapters` / `agents` / `actions`,只有 `<pkg>/plugin.yaml` 一级。

## 3 清单的最小形状

必填 `name`、`version`、`type`、`description`、`class_name`。

```yaml
name: my-plugin
version: 1.0.0
type: adapter              # adapter | agent | action | dashboard_component
description: 一句话说清它做什么
class_name: MyPlugin       # plugin.py 里要实例化的类名

capabilities: [issue.read]
tasks:
  issue.read: read_issue   # 不写就默认把能力的点换成下划线
```

- 同名能力由多个插件提供时,`capabilities_priority` 高者优先;并列直接报错,不按注册顺序猜。
- 只想随包提供、不默认加载,写 `default_enabled: false`,部署时用 `PLUGINS_ENABLED` 打开。
- Hook、UI 插槽、`effects`、`triggers` 的字段见[插件系统参考](../reference/plugin-system.md)。

## 4 写实现

类名必须与 `class_name` 一致,直接 `from engine.plugin_manager.base import ...` 导入——**不要**再改 `sys.path`,加载器已经注入包路径。

```python
from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType


class MyPlugin(PluginBase):
    def info(self) -> PluginInfo:
        return PluginInfo(
            name="my-plugin", version="1.0.0", type=PluginType.ADAPTER,
            description="一句话说清它做什么", capabilities=["issue.read"],
        )

    async def on_startup(self):
        """读配置、建客户端。抛异常只停掉自己,不阻止引擎启动。"""

    async def on_shutdown(self):
        """释放连接。"""

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event: str, data: dict) -> dict:
        """事件订阅入口;没订阅事件时返回 {"status": "ignored"}。"""
        return {"status": "ignored"}

    async def execute_task(self, task: str, params: dict) -> dict:
        """能力入口;task 是清单 `tasks` 映射出来的名字。"""
        if task == "read_issue":
            return {"title": params.get("title", "")}
        return {"status": "error", "message": f"Unknown task: {task}"}
```

## 5 接一个来源:Webhook 适配器

平台只有一个入口:`POST /webhook/{source}`。核心按 `source` 找声明了 `webhook.receive` 的适配器,由它验签并翻译——**接一个新系统不需要改核心的任何一行**。

适配器可以产两种东西,靠 `produces` 声明:

| `produces` | 实现的方法 | 会走到哪 |
| --- | --- | --- |
| `event`(默认) | `parse_webhook(headers, body) -> dict \| None` | `kind` 为 `issue` / `comment` / `merge` 时进对应工作流,`ping` 回 pong,`None` 表示这条投递不关心 |
| `signal` | `parse_signals(headers, body) -> list[dict]` | 逐条去重后进事故管线(`alert_triage_workflow`) |

两种产出共用同一套验签、去重和 503 口径。适配器还要实现三个小方法:

```python
source = "caddy"                  # 入口按 source 名分发
produces = "signal"               # event | signal
config_hint = "CADDY_WEBHOOK_TOKEN"   # 没配密钥时入口告诉你该填哪个变量

def webhook_configured(self) -> bool: ...        # 密钥配了吗
def verify_webhook(self, headers, body) -> bool: # 验签;不过就是 401
```

### 5.1 产事件:一次投递 = 一个归一化事件

事件只有一种说法(`kind` / `repo` / `number` / `title` / `merge_sha` ……),定义在 [events.py](../../engine/ingest/events.py);用 `event(...)` 组装,**形状不对它会当场抛**,不要自己拼字典。

```python
from engine.ingest.events import event as normalized_event, header_value

def parse_webhook(self, headers, body):
    payload = json.loads(body)
    if payload.get("action") != "closed" or not payload.get("merged"):
        return None                       # 不关心的投递:返回 None,不是造一个空事件
    return normalized_event(
        kind="merge", source=self.source,
        repo=payload["repo"], number=payload["pr"], merge_sha=payload["sha"],
        title=payload.get("title", ""),
    )
```

### 5.2 产信号:一次投递 = 零到多条信号

信号回答"哪里出了什么事",不带动作。用 `normalize(...)` 组装,`occurrence` 是单次发作的身份(例如告警的 `startsAt`):同一个 `ref` 再次出现算另一件事,不填则入口按 `ref` 去重。

```python
from engine.ingest.signal import normalize

def parse_signals(self, headers, body):
    payload = json.loads(body)
    if payload.get("state") != "expiring":
        return []                          # 这次没查出什么:空列表,不是一条空事故
    return [normalize(
        source=self.source,
        subject=payload["host"],
        title=f"证书 {payload.get('days_left')} 天后过期",
        detail=payload.get("issuer", ""),
        severity="medium",
        ref=payload["serial"],
        occurrence=payload["checked_at"],
    )]
```

内置的 [alertmanager 适配器](../../plugins/builtin/adapters/alertmanager/plugin.py)是产信号适配器的完整样板,接 Caddy、云雀、Grafana 照它写即可。

### 5.3 自测

```bash
# 装上后看它有没有被认出来(没装适配器的来源会回 503)
curl -sS -X POST http://127.0.0.1:8000/webhook/caddy \
  -H "X-Gwei-Token: $CADDY_WEBHOOK_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"state":"expiring","host":"api.example.com","days_left":3,"serial":"ab12","checked_at":"2026-11-14T03:00:00Z"}'
```

投递不会真的改世界:它只产生一条信号/事件并入队。真正动下游的步骤见下一节,而且仍然要过变更单元的闸门。

## 6 声明一个可撤销的效果

效果声明"这个插件能改什么、怎么撤、怎么验",由核心在加载期校验:缺 `undo`、缺窗口读取来源、验证不可判,注册时就被拒。

```yaml
capabilities: [compose.scale]
tasks:
  compose.scale: scale

effects:
  compose.scale:
    label: 调整 compose 服务副本数
    execute: { task: scale, args: [project_dir, service, replicas] }
    undo: { task: undo_scale, kind: symmetric }
    window: { read: project_present }
    verify:
      - { query: running_replicas, expect: ">= {replicas}", for: 10s }
```

`execute.args` 同时是 intent 提供者的菜单:点一个没声明过的参数,后台只会把它记成阻断。四个方法:

```python
async def execute(self, task: str, args: dict) -> dict:
    """执行并返回 {"handle": ...};没有句柄的效果平台无法兑现撤销。"""

async def undo(self, task: str, args: dict, handle: str) -> dict: ...

async def window(self, effect, handle) -> Window:
    """读,不是声明。读不出来抛异常,平台按不可逆处理。

    三种答案,按下游真实情况给:
      Window(seconds=3600, source="snapshot")                   # 有到期时间
      Window(unbounded=True, source="project_present")          # 目标还在就能撤
      Window(unbounded=True, estimated=True, source="revisions")# 能撤,但按次数/容量淘汰,算不出到期
    """
    from engine.change_unit import Window
    return Window(unbounded=True, source="project_present")

async def verify(self, effect, handle) -> tuple[bool, dict]: ...
```

**抛什么决定这次失败怎么记账。**认得出没碰到下游(构造请求就失败、下游明确 4xx)时抛 `EffectNotApplied`,单元记 `failed`,重试是安全的;抛别的异常一律记 `unknown`——请求可能已经到了对面,重试前得先去下游看一眼。分不清就别猜着抛 `failed`。

窗口的完整口径见[变更单元契约](../explanation/change-unit-contract.md)第 5 节。

## 7 声明一个周期

清单声明"到点跑哪个能力",平台负责把它装进 DBOS 的调度器:

```yaml
capabilities: [scan.dependencies]
triggers:
  - type: schedule
    every: 6h                    # 必须整除分钟 / 小时 / 天,写错在发现阶段就被拒
    capability: scan.dependencies
```

能力必须同时列在 `capabilities` 里。周期换算、幂等与对账规则见[插件系统参考](../reference/plugin-system.md#周期巡检)。

周期适合"只会被问、不会主动说"的来源;能主动投递的系统(绝大多数告警与代码托管)用上一节的 Webhook 适配器,不要绕成轮询。

## 8 配置:不要自己读环境变量

配置走 Scope:字段、必填、能否回显在一处说清,值可以存进业务库,页面上改完立即生效。

```python
from pydantic import BaseModel, Field
from engine.shared.config import config


class MySettings(BaseModel):
    api_key: str = Field(
        ...,                      # 必填;还没填全不算错,由 validate_scope 单独报
        description="控制台里显示的提示:该填什么",
        json_schema_extra={"expose": "never"},   # never | masked | always
    )
    region: str = Field("", json_schema_extra={"expose": "always"})


config.register_model_scope("adapter-my", MySettings, prefix="MY_")
settings = MySettings(**config.get_scope_config("adapter-my", config.settings.default_tenant_slug))
```

顺序是 `Settings` 同名字段 → 环境变量 → `.env` → 库里存的值(库里的排在前面,人在页面上填过的不该被环境变量盖掉)。秘密字段不要 `expose` 成 `always`;要换行(私钥、证书)就加 `"multiline": true`。

## 9 在页面上加一块

两种做法:声明式卡片(核心渲染,零代码、安全)与 iframe 整页(任意技术栈)。

### 9.1 卡片进槽位

槽位由核心声明,插件只能往里放——写了不存在的槽位,加载期就拒:

| 槽位 | 出现在 |
| --- | --- |
| `issue-board.bento` | 首页议题板的卡片列 |
| `issue-detail.sidebar` | Issue 详情页右栏 |
| `settings.plugins` | 设置页底部 |

```yaml
ui:
  widgets:
    - slot: issue-board.bento
      kind: metric            # metric | list
      span: 2                 # 1-4,占几列
      title: 变更风险
      metrics:
        - { label: 夜间自动变更, value: 12, sub: 近 7 天, variant: green }
```

`list` 用 `items`(每项 `{text: "..."}`)。卡片是数据,不是代码:配色只有 default / green / yellow / red 四档——要复杂界面走下一节。

### 9.2 整页进 iframe

```yaml
ui:
  pages:
    - title: 扩缩容策略
      entry: index.html
```

资产放插件目录的 `ui/` 下,前端经 `/plugins/<name>` 用 `<iframe sandbox="allow-scripts">` 加载,资产由 `GET /api/plugins/{name}/ui/{path}` 提供(路径解析后必须仍在插件 `ui/` 目录内)。主应用 bundle 永远不接受插件注入的可执行代码。

## 10 验证

```bash
# 1) 清单与实现能被加载(坏清单会被跳过并计数,不会拖垮其余插件)
python -c "from engine.plugin_manager import registry; print(registry.discover())"

# 2) 全量测试
python -m pytest tests/ -q
```

写测试时照着这几份抄:

- 适配器与入口:[test_alert_signal.py](../../tests/test_integration/test_alert_signal.py)(含"新来源不改核心"的用例)
- 清单校验:[test_scheduler.py](../../tests/test_integration/test_scheduler.py)、[test_plugin_system.py](../../tests/test_integration/test_plugin_system.py)
- 效果与撤销:[test_change_unit.py](../../tests/test_integration/test_change_unit.py)、[test_undo_window.py](../../tests/test_integration/test_undo_window.py)
- 配置回显:[test_plugin_config_scope.py](../../tests/test_integration/test_plugin_config_scope.py)

## 11 常见失败

| 症状 | 原因 |
| --- | --- |
| 插件没加载,日志里只有一行 `plugin_discovery_errors_total` | 清单缺必填字段、`class_name` 对不上、`effects` 缺 `undo`、周期不整除 |
| Webhook 回 503 | 没装适配器,或适配器 `webhook_configured()` 为假(密钥没填) |
| Webhook 回 401 | `verify_webhook()` 没过:签名/令牌算法与来源不一致 |
| Webhook 回 400 | `parse_signals` 抛了:投递不是 JSON、或信号缺 `subject` / `title` |
| 投递回 200 但没有工作流 | 产事件时返回了 `None`、`kind` 不在这四类里,或信号被去重(同一 `ref + occurrence`) |
| 效果被记成 `blocked` | 能力没人提供、缺 `binding`、或 intent 点了清单里没声明的参数 |
| 改了环境变量但没生效 | 配置可能已经在库里存过——库里的值优先;去控制台改,或删掉库里的配置项 |