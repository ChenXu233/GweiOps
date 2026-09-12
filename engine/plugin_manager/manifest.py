# engine/plugin_manager/manifest.py
"""插件清单(Manifest v2)——插件与外界唯一的声明式合同。

清单是闭源插件与平台之间的唯一契约:名称、类型、事件订阅、能力(含覆盖优先级
与任务名映射)、Hook 订阅与发布。加载期全部校验,坏清单拒绝注册。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .base import PluginType

HOOK_MODES = ("observe", "transform", "veto")
HOOK_FAILURE_MODES = ("fail_open", "fail_closed")


class ManifestError(ValueError):
    """清单缺失必填字段或含非法值。"""


@dataclass
class HookSubscription:
    """对某扩展点的一次订阅。"""

    point: str
    mode: str = "observe"  # observe | transform | veto
    priority: int = 0
    failure_mode: str = "fail_open"  # fail_open | fail_closed
    handler: str = "handle_hook"  # 插件实例上的方法名


@dataclass
class Manifest:
    name: str
    version: str
    type: PluginType
    description: str
    class_name: str
    triggers: list[dict[str, Any]] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    hooks_offered: list[str] = field(default_factory=list)
    hooks_subscribed: list[HookSubscription] = field(default_factory=list)
    capabilities_priority: dict[str, int] = field(default_factory=dict)
    tasks: dict[str, str] = field(default_factory=dict)  # capability -> execute_task 任务名

    @property
    def event_subscriptions(self) -> list[str]:
        """triggers 中声明的事件订阅(event 类型)。"""
        return [
            event
            for trigger in self.triggers
            if trigger.get("type") == "event"
            for event in trigger.get("events", [])
        ]

    @classmethod
    def from_yaml(cls, path: Path) -> "Manifest":
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ManifestError(f"{path}: 清单必须是 YAML 映射")

        for key in ("name", "version", "type", "description", "class_name"):
            if not raw.get(key):
                raise ManifestError(f"{path}: 缺少必填字段 {key}")
        try:
            plugin_type = PluginType(raw["type"])
        except ValueError:
            raise ManifestError(f"{path}: 非法插件类型 {raw['type']}") from None

        hooks_raw = raw.get("hooks") or {}
        subscriptions: list[HookSubscription] = []
        for sub in hooks_raw.get("subscribe", []):
            if sub.get("mode", "observe") not in HOOK_MODES:
                raise ManifestError(f"{path}: 非法 hook mode {sub.get('mode')}")
            if sub.get("failure_mode", "fail_open") not in HOOK_FAILURE_MODES:
                raise ManifestError(
                    f"{path}: 非法 hook failure_mode {sub.get('failure_mode')}"
                )
            if not sub.get("point"):
                raise ManifestError(f"{path}: hook 订阅缺少 point")
            subscriptions.append(
                HookSubscription(
                    point=sub["point"],
                    mode=sub.get("mode", "observe"),
                    priority=int(sub.get("priority", 0)),
                    failure_mode=sub.get("failure_mode", "fail_open"),
                    handler=sub.get("handler", "handle_hook"),
                )
            )
        for point in hooks_raw.get("offered", []):
            if not point:
                raise ManifestError(f"{path}: hooks.offered 含空扩展点")

        return cls(
            name=raw["name"],
            version=str(raw["version"]),
            type=plugin_type,
            description=raw["description"],
            class_name=raw["class_name"],
            triggers=list(raw.get("triggers") or []),
            capabilities=list(raw.get("capabilities") or []),
            hooks_offered=list(hooks_raw.get("offered") or []),
            hooks_subscribed=subscriptions,
            capabilities_priority={
                str(k): int(v) for k, v in (raw.get("capabilities_priority") or {}).items()
            },
            tasks={str(k): str(v) for k, v in (raw.get("tasks") or {}).items()},
        )
