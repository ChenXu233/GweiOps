# engine/plugin_manager/manifest.py
"""插件清单(Manifest v2)——插件与外界唯一的声明式合同。

清单是插件与平台之间的唯一契约:名称、类型、事件订阅、能力(含覆盖优先级
与任务名映射)、Hook 订阅与发布。加载期全部校验,坏清单拒绝注册。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .base import PluginType
from .slots import known_slot, slot_hint

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
    execute_args: tuple[str, ...] = ()  # 这次效果认识的参数名,给 intent 提供者当菜单

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
            verify=tuple(dict(rule) for rule in self.verify),
        )


SCHEDULE_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


@dataclass(frozen=True)
class ScheduleDecl:
    """清单里的一条周期声明:到点跑哪个能力。

    周期写成 `every`(如 "6h"),不收 cron:cron 的 * 与步长读不出"多久一次",
    也读不出"会不会漏"。核心里只保留秒数,换算成调度器认的表达式是调度层的事。
    """

    capability: str
    every_s: int


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
    triggers: list[dict[str, Any]] = field(default_factory=list)  # 原样保留,索引见下
    schedules: tuple[ScheduleDecl, ...] = ()  # triggers 里 type: schedule 的解析结果
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
            # 槽位由核心声明:写错的名字不会在页面上"什么都不显示",而是当场被拒。
            if not known_slot(str(w["slot"])):
                raise ManifestError(
                    f"{path}: ui.widget 的槽位 {w['slot']!r} 不存在;已知槽位:{slot_hint()}"
                )
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
        schedules = _parse_schedules(
            path, list(raw.get("triggers") or []), list(raw.get("capabilities") or [])
        )

        return cls(
            name=raw["name"],
            version=str(raw["version"]),
            type=plugin_type,
            description=raw["description"],
            class_name=raw["class_name"],
            default_enabled=bool(raw.get("default_enabled", True)),
            triggers=list(raw.get("triggers") or []),
            schedules=schedules,
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


def _parse_every(path: Path, value: Any) -> int:
    """周期转秒数。写不清的周期在加载期就拒,不让它拖到调度器第一次点火。"""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ManifestError(f"{path}: schedule.every 必须是秒数或带单位的时长: {value!r}")

    if isinstance(value, int):
        seconds = value
    else:
        text = value.strip().lower()
        unit = text[-1:] if text else ""
        if unit in SCHEDULE_UNITS:
            number, factor = text[:-1], SCHEDULE_UNITS[unit]
        else:
            number, factor = text, 1
        try:
            seconds = int(float(number) * factor)
        except ValueError:
            raise ManifestError(f"{path}: schedule.every 读不出时长: {value!r}") from None

    if seconds <= 0:
        raise ManifestError(f"{path}: schedule.every 必须大于 0: {value!r}")
    return seconds


def _parse_schedules(
    path: Path, triggers: list[Any], capabilities: list[str]
) -> tuple[ScheduleDecl, ...]:
    """`triggers: [{type: schedule, every: 6h, capability: scan.dependencies}]`。

    周期必须整除它所在的那一档(分钟 / 小时 / 天):不整除的"每 45 分钟"在
    任何按整点对齐的调度器上都会走成 45 分钟、15 分钟、45 分钟。与其跑出一个
    看着像均匀的假象,不如在加载期说清楚。
    """
    out: list[ScheduleDecl] = []
    for trigger in triggers:
        if not isinstance(trigger, dict) or trigger.get("type") != "schedule":
            continue

        capability = str(trigger.get("capability") or "").strip()
        if not capability:
            raise ManifestError(f"{path}: schedule 触发缺少 capability")
        if capability not in capabilities:
            raise ManifestError(
                f"{path}: schedule 声明了能力 {capability},但它不在 capabilities 里"
            )

        seconds = _parse_every(path, trigger.get("every"))
        if seconds < 60:
            fits = 60 % seconds == 0
        elif seconds < 3600:
            fits = seconds % 60 == 0 and 3600 % seconds == 0
        elif seconds == 86400:
            fits = True
        else:
            fits = seconds % 3600 == 0 and 86400 % seconds == 0
        if not fits:
            raise ManifestError(
                f"{path}: schedule.every={seconds}s 不整除分钟/小时/天,"
                "排出来的周期会忽长忽短;改成能整除的时长"
            )

        out.append(ScheduleDecl(capability=capability, every_s=seconds))
    return tuple(out)


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
        args = execute.get("args") or []
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ManifestError(
                f"{path}: effect {capability} 的 execute.args 必须是字符串列表"
            )

        out[capability] = EffectDecl(
            capability=capability,
            execute_task=execute["task"],
            undo_task=undo["task"],
            undo_kind=undo.get("kind", "retained"),
            window_read=window["read"],
            verify=tuple(verify),
            label=spec.get("label", ""),
            execute_args=tuple(args),
        )
    return out
