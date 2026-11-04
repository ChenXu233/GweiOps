# 写一个插件

> 状态:现行 | 日期:2026-11-02
> 读者:插件作者
> 上游:[插件系统参考](../reference/plugin-system.md)

## 1. 放哪里

内置插件放在仓库的 `plugins/builtin/` 下,一个插件一个目录:

```text
plugins/builtin/
  adapters/<plugin>/plugin.yaml + plugin.py
  agents/<plugin>/plugin.yaml + plugin.py
  actions/<plugin>/plugin.yaml + plugin.py
```

外部插件用 `PLUGINS_EXTRA_DIRS`(冒号分隔)指定根;根下每个 `<pkg>/plugin.yaml` 是一个插件。

## 2. 写清单

`plugin.yaml` 是唯一合同;必填 name、version、type、description、class_name。

```yaml
name: my-plugin
version: 1.0.0
type: adapter
description: My custom adapter
class_name: MyPlugin

triggers:
  - type: event
    events: [issue.created]

capabilities: [issue.read]
tasks:
  issue.read: read_issue
```

- `tasks` 把能力名映射到 `execute_task` 的任务名;不写时默认把能力名的点换成下划线。
- 同名能力可由多个插件提供,用 `capabilities_priority` 决定谁优先。
- Hook 与 UI 插槽字段见 [插件系统参考](../reference/plugin-system.md)。

## 3. 写实现

`plugin.py` 里的类名必须与清单的 `class_name` 一致:

```python
from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType


class MyPlugin(PluginBase):
    def info(self) -> PluginInfo:
        return PluginInfo(
            name="my-plugin",
            version="1.0.0",
            type=PluginType.ADAPTER,
            description="My custom adapter",
        )

    async def on_startup(self):
        pass

    async def on_shutdown(self):
        pass

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event: str, data: dict) -> dict:
        return {"status": "ok"}

    async def execute_task(self, task: str, params: dict) -> dict:
        if task == "read_issue":
            return {"title": params.get("title", "")}
        return {"status": "unknown-task", "task": task}
```

直接 `from engine.plugin_manager.base import ...` 导入;**不要**再改 `sys.path`。插件加载器已经把包路径注入。

## 4. 接能力与事件

- 能力:清单声明 `capabilities` + `tasks`;调用方用 `registry.run_capability("issue.read", params)`,不需要知道插件是谁。
- 事件:清单 `triggers[].type=event` 的 `events` 会被注册;发布方用 `events.publish("issue.created", payload)`。
- Hook:在 `hooks.subscribe` 声明扩展点与 mode;默认 handler 名为 `handle_hook`。
- UI:在 `ui.widgets` / `ui.pages` 声明;页面资产放插件目录的 `ui/` 下。

## 5. 验证

```bash
# 插件被正确发现、实例化并注册能力
python -c "from engine.plugin_manager import registry; print(registry.discover())"

# 全量测试
pytest tests/ -q
```

常见失败:

- 清单缺 `class_name` 或 `plugin.py` 里没有该类 → 该插件被跳过,其他插件继续加载;
- 两个插件同名 → 注册直接报错;
- 用了 `sys.path.insert` → 外部根插件会加载失败,按第 3 节改成正常导入。
