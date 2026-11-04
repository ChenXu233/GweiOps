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


EFFECT_UNDO_KINDS = ("retained", "symmetric")


@dataclass(frozen=True)
class EffectDecl:
    """一个效果声明:谁能改什么、怎么撤、怎么验。

    声明权在清单,执行权在插件。核心在加载期解析并校验,坏的直接拒绝注册——
    不让它拖到真去执行时才炸。
    """

    capability: str
    execute_task: str
    undo_task: str
    undo_kind: str = "retained"
    window_read: str = ""
    verify: tuple[dict[str, Any], ...] = ()
    label: str = ""

    def to_effect(self, args: dict[str, Any]):
        """按声明构造一次待执行的效果(引用,不含实现)。"""
        from engine.change_unit.model import Effect

        return Effect(
            task=self.execute_task,
            args=dict(args),
            undo_task=self.undo_task,
            undo_kind=self.undo_kind,
            label=self.label,
            capability=self.capability,
        )


@dataclass
class HookSubscription:
    """对某扩展点的一次订阅。"""

    point: str
    mode: str = "observe"  # observe | transform | veto
    priority: int = 0
    failure_mode: str = "fail_open"  # fail_open | fail_closed
    handler: str = "handle_hook"  # 插件实例上的方法名


@dataclass
class UiPage:
    """插件经 iframe 沙箱提供的完整页面(静态资产由 engine 服务)。"""

    title: str
    entry: str = "index.html"

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "entry": self.entry}


UI_WIDGET_KINDS = ("metric", "list")
UI_VARIANTS = ("default", "green", "yellow", "red")


@dataclass
class UiWidget:
    """声明式 UI 卡片——由核心前端按 schema 渲染,插件不注入代码。"""

    slot: str
    kind: str = "metric"  # metric | list
    span: int = 1  # 1..4(BentoGrid 列跨度)
    title: str = ""
    metrics: list[dict[str, Any]] = field(default_factory=list)  # {label,value,sub?,variant?}
    items: list[dict[str, Any]] = field(default_factory=list)  # {text}

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "kind": self.kind,
            "span": self.span,
            "title": self.title,
            "metrics": self.metrics,
            "items": self.items,
        }


@dataclass
class Manifest:
    name: str
    version: str
    type: PluginType
    description: str
    class_name: str
    default_enabled: bool = True  # 部署未显式选择时是否加载;false 表示备选项
    triggers: list[dict[str, Any]] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    hooks_offered: list[str] = field(default_factory=list)
    hooks_subscribed: list[HookSubscription] = field(default_factory=list)
    capabilities_priority: dict[str, int] = field(default_factory=dict)
    tasks: dict[str, str] = field(default_factory=dict)  # capability -> execute_task 任务名
    ui_widgets: list[UiWidget] = field(default_factory=list)
    ui_pages: list[UiPage] = field(default_factory=list)
    effects: dict[str, EffectDecl] = field(default_factory=dict)

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

        ui_raw = raw.get("ui") or {}
        widgets: list[UiWidget] = []
        for w in ui_raw.get("widgets", []):
            if not w.get("slot"):
                raise ManifestError(f"{path}: ui.widget 缺少 slot")
            if w.get("kind", "metric") not in UI_WIDGET_KINDS:
                raise ManifestError(f"{path}: 非法 widget kind {w.get('kind')}")
            span = int(w.get("span", 1))
            if not 1 <= span <= 4:
                raise ManifestError(f"{path}: widget span 超出 1-4: {span}")
            for metric in w.get("metrics", []):
                variant = metric.get("variant", "default")
                if variant not in UI_VARIANTS:
                    raise ManifestError(f"{path}: 非法 widget variant {variant}")
            widgets.append(
                UiWidget(
                    slot=w["slot"],
                    kind=w.get("kind", "metric"),
                    span=span,
                    title=w.get("title", ""),
                    metrics=list(w.get("metrics") or []),
                    items=list(w.get("items") or []),
                )
            )
        pages_raw = ui_raw.get("pages") or []
        pages: list[UiPage] = []
        for p in pages_raw:
            if not p.get("title"):
                raise ManifestError(f"{path}: ui.page 缺少 title")
            entry = p.get("entry", "index.html")
            # 路径安全:禁绝对路径、.. 段与反斜杠,防 iframe 资产穿越
            if (
                not entry
                or "\\" in entry
                or entry.startswith("/")
                or any(seg == ".." for seg in entry.split("/"))
            ):
                raise ManifestError(f"{path}: 非法 ui.page entry {entry!r}")
            pages.append(UiPage(title=p["title"], entry=entry))

        effects = _parse_effects(path, raw.get("effects") or {})

        return cls(
            name=raw["name"],
            version=str(raw["version"]),
            type=plugin_type,
            description=raw["description"],
            class_name=raw["class_name"],
            default_enabled=bool(raw.get("default_enabled", True)),
            triggers=list(raw.get("triggers") or []),
            capabilities=list(raw.get("capabilities") or []),
            hooks_offered=list(hooks_raw.get("offered") or []),
            hooks_subscribed=subscriptions,
            capabilities_priority={
                str(k): int(v) for k, v in (raw.get("capabilities_priority") or {}).items()
            },
            tasks={str(k): str(v) for k, v in (raw.get("tasks") or {}).items()},
            ui_widgets=widgets,
            ui_pages=pages,
            effects=effects,
        )


def _parse_effects(path: Path, raw: Any) -> dict[str, EffectDecl]:
    """解析 effects 块。形状不对即拒绝注册——坏声明不该活到执行期。"""
    if not isinstance(raw, dict):
        raise ManifestError(f"{path}: effects 必须是映射")

    out: dict[str, EffectDecl] = {}
    for capability, spec in raw.items():
        if not isinstance(spec, dict):
            raise ManifestError(f"{path}: effect {capability} 必须是映射")

        execute = spec.get("execute") or {}
        undo = spec.get("undo") or {}
        window = spec.get("window") or {}
        verify = spec.get("verify") or []

        if not execute.get("task"):
            raise ManifestError(f"{path}: effect {capability} 缺少 execute.task")
        if not undo.get("task"):
            raise ManifestError(f"{path}: effect {capability} 缺少 undo.task")
        if undo.get("kind", "retained") not in EFFECT_UNDO_KINDS:
            raise ManifestError(f"{path}: effect {capability} 的 undo.kind 非法")
        if not window.get("read"):
            raise ManifestError(f"{path}: effect {capability} 缺少 window.read")
        if not isinstance(verify, list) or not verify:
            raise ManifestError(f"{path}: effect {capability} 至少要有一条 verify")
        for rule in verify:
            if not isinstance(rule, dict) or not rule.get("query") or "expect" not in rule:
                raise ManifestError(
                    f"{path}: effect {capability} 的 verify 必须是 {{query, expect}}"
                )

        out[capability] = EffectDecl(
            capability=capability,
            execute_task=execute["task"],
            undo_task=undo["task"],
            undo_kind=undo.get("kind", "retained"),
            window_read=window["read"],
            verify=tuple(verify),
            label=spec.get("label", ""),
        )
    return out
