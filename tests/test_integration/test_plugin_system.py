# tests/test_integration/test_plugin_system.py
"""插件系统 v2 测试:manifest、发现与隔离、事件总线、Hook 管线。"""

import asyncio
import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 工具:在临时目录构造可导入的假插件
# ---------------------------------------------------------------------------

PLUGIN_TEMPLATE = """
from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType


class {class_name}(PluginBase):
    mode = "{hook_mode}"          # handle_hook 行为
    broken_on_event = {broken_on_event}

    def info(self):
        return PluginInfo(
            name="{name}", version="1.0.0", type=PluginType.AGENT,
            description="test", triggers=[], capabilities={capabilities!r},
        )

    async def on_startup(self):
        self.started = True

    async def on_shutdown(self):
        pass

    async def health_check(self):
        return True

    async def handle_event(self, event, data):
        self.calls = getattr(self, "calls", [])
        self.calls.append((event, data))
        if self.broken_on_event:
            raise RuntimeError("boom")

    async def execute_task(self, task, params):
        return {{"task": task}}

    async def handle_hook(self, point, payload):
        if self.mode == "transform":
            payload = dict(payload)
            payload["v"] = payload.get("v", 0) + 1
            return payload
        if self.mode == "veto":
            return False
        return None  # observe
"""


def make_plugin(
    root: Path,
    pkg: str,
    name: str,
    *,
    class_name: str | None = None,
    capabilities: list[str] | None = None,
    priority: int | None = None,
    events: list[str] | None = None,
    hook_mode: str = "observe",
    hook_subscribe: list[dict] | None = None,
    broken_on_event: bool = False,
    extra_yaml: str = "",
    broken_import: bool = False,
) -> None:
    pkg_dir = root / pkg
    pkg_dir.mkdir(parents=True, exist_ok=True)
    class_name = class_name or ("".join(p.title() for p in name.split("-")).replace("_", ""))

    plugin_body = PLUGIN_TEMPLATE.format(
        class_name=class_name,
        name=name,
        capabilities=capabilities or [],
        hook_mode=hook_mode,
        broken_on_event=broken_on_event,
    )
    if broken_import:
        plugin_body = "import nonexistent_module_xyz\n" + plugin_body
    (pkg_dir / "plugin.py").write_text(textwrap.dedent(plugin_body), encoding="utf-8")

    lines = [
        f"name: {name}",
        "version: 1.0.0",
        "type: agent",
        f"class_name: {class_name}",
        "description: test plugin",
    ]
    if events:
        lines.append("triggers:")
        lines.append("  - type: event")
        lines.append("    events:")
        lines.extend(f"      - {e}" for e in events)
    if capabilities:
        lines.append(f"capabilities: {capabilities!r}")
    if priority is not None and capabilities:
        lines.append("capabilities_priority:")
        lines.extend(f"  {c}: {priority}" for c in capabilities)
    if capabilities:
        lines.append("tasks:")
        lines.extend(f"  {c}: task_{c.replace('.', '_')}" for c in capabilities)
    if hook_subscribe:
        lines.append("hooks:")
        lines.append("  subscribe:")
        for sub in hook_subscribe:
            lines.append(f"    - point: {sub['point']}")
            lines.append(f"      mode: {sub.get('mode', 'observe')}")
            lines.append(f"      priority: {sub.get('priority', 0)}")
            lines.append(f"      failure_mode: {sub.get('failure_mode', 'fail_open')}")
    lines.append(extra_yaml)

    (pkg_dir / "plugin.yaml").write_text("\n".join(lines), encoding="utf-8")


@pytest.fixture()
def plugin_root(tmp_path, monkeypatch):
    """独立的插件根 + 干净的 sys.path。"""
    monkeypatch.syspath_prepend(str(tmp_path))
    yield tmp_path
    for mod in [m for m in list(__import__("sys").modules) if m.startswith(tuple(p.name for p in tmp_path.iterdir()))]:
        del __import__("sys").modules[mod]


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


class TestManifest:
    def test_real_fixer_manifest(self):
        from engine.plugin_manager.manifest import Manifest

        m = Manifest.from_yaml(Path("plugins/builtin/agents/fixer/plugin.yaml"))
        assert m.class_name == "FixerAgent"
        assert m.tasks["patch.generate"] == "generate_patches"
        # 订阅的事件必须真有人发布;当前核心不发布任何事件
        assert m.event_subscriptions == []

    def test_missing_field_rejected(self, tmp_path):
        from engine.plugin_manager.manifest import Manifest, ManifestError

        p = tmp_path / "plugin.yaml"
        p.write_text("name: x\nversion: 1.0.0\ntype: agent\n")
        with pytest.raises(ManifestError):
            Manifest.from_yaml(p)

    def test_invalid_hook_mode_rejected(self, tmp_path):
        from engine.plugin_manager.manifest import Manifest, ManifestError

        p = tmp_path / "plugin.yaml"
        p.write_text(
            "name: x\nversion: 1.0.0\ntype: agent\nclass_name: X\n"
            "description: d\nhooks:\n  subscribe:\n    - point: p\n      mode: monkey_patch\n"
        )
        with pytest.raises(ManifestError):
            Manifest.from_yaml(p)

    def test_event_subscriptions_derived(self, plugin_root):
        from engine.plugin_manager.manifest import Manifest

        make_plugin(plugin_root, "pkgev", "ev-plugin", events=["e1", "e2"])
        m = Manifest.from_yaml(plugin_root / "pkgev" / "plugin.yaml")
        assert m.event_subscriptions == ["e1", "e2"]


# ---------------------------------------------------------------------------
# 发现与索引
# ---------------------------------------------------------------------------


class TestRegistryDiscovery:
    def test_discover_and_indexes(self, plugin_root):
        from engine.plugin_manager.registry import PluginRegistry

        make_plugin(
            plugin_root, "pkg1", "cap-plugin",
            capabilities=["patch.generate"], priority=5,
            events=["sensor.processed"],
        )
        registry = PluginRegistry()
        count = registry.discover(builtin_dir=plugin_root)

        assert count == 1
        assert registry.get("cap-plugin") is not None
        assert [i for i in registry.instances_for_event("sensor.processed")] != []
        provider = registry.best_capability_provider("patch.generate")
        assert provider is not None

    def test_broken_import_isolated(self, plugin_root):
        from engine.plugin_manager.registry import PluginRegistry

        make_plugin(plugin_root, "good", "good-plugin")
        make_plugin(plugin_root, "bad", "bad-plugin", broken_import=True)

        registry = PluginRegistry()
        count = registry.discover(builtin_dir=plugin_root)

        assert count == 1
        assert registry.get("good-plugin") is not None
        assert registry.get("bad-plugin") is None

    def test_duplicate_name_skipped(self, plugin_root):
        from engine.plugin_manager.registry import PluginRegistry

        make_plugin(plugin_root, "pkg_a", "dup-plugin")
        make_plugin(plugin_root, "pkg_b", "dup-plugin")

        registry = PluginRegistry()
        assert registry.discover(builtin_dir=plugin_root) == 1

    def test_capability_priority_and_task_mapping(self, plugin_root):
        from engine.plugin_manager.registry import PluginRegistry

        make_plugin(
            plugin_root, "low", "low-plugin",
            capabilities=["patch.generate"], priority=1,
        )
        make_plugin(
            plugin_root, "high", "high-plugin",
            capabilities=["patch.generate"], priority=9,
        )
        registry = PluginRegistry()
        registry.discover(builtin_dir=plugin_root)

        winner = registry.best_capability_provider("patch.generate")
        assert type(winner).__name__ == "HighPlugin"

        result = asyncio.run(registry.run_capability("patch.generate", {}))
        # tasks 映射生效:任务名应为 task_patch_generate(而非 patch_generate)
        assert result == {"task": "task_patch_generate"}


# ---------------------------------------------------------------------------
# 事件总线
# ---------------------------------------------------------------------------


class TestEventBus:
    def test_fanout_with_isolation_and_metrics(self, plugin_root):
        from engine.shared.metrics import metrics as collector
        from engine.plugin_manager.events import EventBus
        from engine.plugin_manager.registry import PluginRegistry

        make_plugin(plugin_root, "ok", "ok-plugin", events=["e1"])
        make_plugin(plugin_root, "bad", "bad-plugin", events=["e1"], broken_on_event=True)

        registry = PluginRegistry()
        registry.discover(builtin_dir=plugin_root)
        ok_instance = registry.get("ok-plugin")

        bus = EventBus(registry)
        completed = asyncio.run(bus.publish("e1", {"v": 1}))

        assert completed == 1
        assert ok_instance.calls == [("e1", {"v": 1})]
        counters = {
            (m.name, tuple(sorted(m.labels.items()))): m.value
            for m in collector.get_metrics()
            if m.name.startswith("plugin_event")
        }
        assert counters[("plugin_events_published_total", (("event", "e1"),))] == 1
        assert counters[
            ("plugin_event_handler_errors_total", (("kind", "error"), ("plugin", "BadPlugin")))
        ] == 1

    def test_handler_timeout_isolated(self, plugin_root):
        from engine.plugin_manager.events import EventBus
        from engine.plugin_manager.registry import PluginRegistry

        make_plugin(plugin_root, "slow", "slow-plugin", events=["e1"])

        registry = PluginRegistry()
        registry.discover(builtin_dir=plugin_root)
        instance = registry.get("slow-plugin")

        async def hang(self, event, data):
            await asyncio.sleep(5)

        instance.handle_event = hang.__get__(instance)

        bus = EventBus(registry, timeout_s=0.1)
        completed = asyncio.run(bus.publish("e1", {}))
        assert completed == 0


# ---------------------------------------------------------------------------
# Hook 管线
# ---------------------------------------------------------------------------


class TestHookPipeline:
    def _registry_with(self, plugin_root, spec):
        from engine.plugin_manager.hooks import HookPipeline
        from engine.plugin_manager.registry import PluginRegistry

        for pkg, name, mode, priority, failure in spec:
            make_plugin(
                plugin_root, pkg, name,
                hook_mode=mode,
                hook_subscribe=[{"point": "comment.posting", "mode": mode,
                                 "priority": priority, "failure_mode": failure}],
            )
        registry = PluginRegistry()
        registry.discover(builtin_dir=plugin_root)
        return HookPipeline(registry)

    def test_transform_chains_in_priority_order(self, plugin_root):
        spec = [
            ("low", "hook-low", "transform", 1, "fail_open"),
            ("high", "hook-high", "transform", 9, "fail_open"),
        ]
        hooks = self._registry_with(plugin_root, spec)
        result = asyncio.run(hooks.apply("comment.posting", {"v": 0}))

        assert result["allowed"] is True
        # 两个 transform 都执行:高优先级先 +1,低优先级后 +1
        assert result["payload"]["v"] == 2

    def test_veto_short_circuits(self, plugin_root):
        spec = [("v", "hook-veto", "veto", 5, "fail_open")]
        hooks = self._registry_with(plugin_root, spec)
        result = asyncio.run(hooks.apply("comment.posting", {"v": 0}))

        assert result["allowed"] is False

    def test_fail_closed_exception_blocks(self, plugin_root):
        # observe 模式 + fail_closed:handler 抛异常时按 veto 处理
        from engine.plugin_manager.registry import PluginRegistry
        from engine.plugin_manager.hooks import HookPipeline

        make_plugin(
            plugin_root, "fc", "fc-plugin", hook_mode="observe",
            hook_subscribe=[{"point": "comment.posting", "mode": "observe",
                             "priority": 0, "failure_mode": "fail_open"}],
        )
        registry = PluginRegistry()
        registry.discover(builtin_dir=plugin_root)

        instance = registry.get("fc-plugin")

        async def boom(self, point, payload):
            raise RuntimeError("x")

        instance.handle_hook = boom.__get__(instance)
        # 直接改订阅声明为 fail_closed
        registry._manifests["fc-plugin"].hooks_subscribed[0].failure_mode = "fail_closed"

        hooks = HookPipeline(registry)
        result = asyncio.run(hooks.apply("comment.posting", {"v": 0}))

        assert result["allowed"] is False

    def test_fail_open_exception_skips(self, plugin_root):
        from engine.plugin_manager.registry import PluginRegistry
        from engine.plugin_manager.hooks import HookPipeline

        make_plugin(
            plugin_root, "fo", "fo-plugin", hook_mode="transform",
            hook_subscribe=[{"point": "comment.posting", "mode": "transform",
                             "priority": 0, "failure_mode": "fail_open"}],
        )
        registry = PluginRegistry()
        registry.discover(builtin_dir=plugin_root)

        instance = registry.get("fo-plugin")

        async def boom(self, point, payload):
            raise RuntimeError("x")

        instance.handle_hook = boom.__get__(instance)

        hooks = HookPipeline(registry)
        result = asyncio.run(hooks.apply("comment.posting", {"v": 7}))

        assert result["allowed"] is True
        assert result["payload"] == {"v": 7}  # transform 被跳过,载荷不变
