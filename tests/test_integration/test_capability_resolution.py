# tests/test_integration/test_capability_resolution.py
"""能力解析:按 (租户, 目标) 精确选择提供者,不跨目标回退。"""

from __future__ import annotations

import asyncio

import pytest

from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType
from engine.plugin_manager.manifest import Manifest
from engine.plugin_manager.registry import PluginRegistry


class FakePlugin(PluginBase):
    def __init__(self, tag: str, tenant: str = "", binding: str = "") -> None:
        self.tag = tag
        self.tenant = tenant
        self.binding = binding

    def info(self) -> PluginInfo:
        return PluginInfo(
            name=self.tag, version="1.0.0", type=PluginType.AGENT, description="fake"
        )

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event, data):
        return {}

    async def execute_task(self, task, params):
        return {"tag": self.tag, "task": task}


def _manifest(name: str, capability: str, task: str, priority: int = 0) -> Manifest:
    return Manifest(
        name=name,
        version="1.0.0",
        type=PluginType.AGENT,
        description="fake",
        class_name="FakePlugin",
        capabilities=[capability],
        tasks={capability: task},
        capabilities_priority={capability: priority},
    )


def _registry_with_two_targets() -> PluginRegistry:
    reg = PluginRegistry()
    reg.register(
        _manifest("compose-a", "compose.scale", "scale_a", priority=1),
        FakePlugin("a", tenant="tenant-a", binding="target-a"),
    )
    reg.register(
        _manifest("compose-b", "compose.scale", "scale_b", priority=9),
        FakePlugin("b", tenant="tenant-b", binding="target-b"),
    )
    reg.register(
        _manifest("control", "issue.read", "read_issue"),
        FakePlugin("control"),
    )
    return reg


def test_resolve_prefers_exact_target_over_priority():
    reg = _registry_with_two_targets()
    provider = reg.resolve("compose.scale", tenant="tenant-a", binding="target-a")
    assert provider.tag == "a"  # 优先级低,但目标对


def test_resolve_never_falls_back_to_another_target():
    reg = _registry_with_two_targets()
    with pytest.raises(LookupError, match="available"):
        reg.resolve("compose.scale", tenant="tenant-c", binding="target-c")


def test_control_plane_capability_resolves_with_empty_target():
    reg = _registry_with_two_targets()
    provider = reg.resolve("issue.read", tenant="", binding="")
    assert provider.tag == "control"


def test_run_capability_routes_to_target_and_uses_its_task_name():
    reg = _registry_with_two_targets()
    result = asyncio.run(
        reg.run_capability("compose.scale", {}, tenant="tenant-b", binding="target-b")
    )
    assert result == {"tag": "b", "task": "scale_b"}


def test_run_capability_without_target_keeps_legacy_priority():
    reg = _registry_with_two_targets()
    result = asyncio.run(reg.run_capability("compose.scale", {}))
    assert result["tag"] == "b"  # 全局优先级最高的仍是 b


def test_capability_bindings_lists_all_providers():
    reg = _registry_with_two_targets()
    rows = reg.capability_bindings("compose.scale")
    assert {(name, tenant, binding) for name, tenant, binding, _ in rows} == {
        ("compose-a", "tenant-a", "target-a"),
        ("compose-b", "tenant-b", "target-b"),
    }


def test_one_manifest_can_serve_multiple_tenants():
    reg = PluginRegistry()
    manifest = _manifest("compose", "compose.scale", "scale")
    reg.register(
        manifest, FakePlugin("a", tenant="t-a", binding="b-a"), key="compose@t-a/b-a"
    )
    reg.register(
        manifest, FakePlugin("b", tenant="t-b", binding="b-b"), key="compose@t-b/b-b"
    )
    assert reg.resolve("compose.scale", tenant="t-a", binding="b-a").tag == "a"
    assert reg.resolve("compose.scale", tenant="t-b", binding="b-b").tag == "b"
    assert set(reg.names()) == {"compose@t-a/b-a", "compose@t-b/b-b"}


def test_same_name_with_different_manifest_is_rejected():
    reg = PluginRegistry()
    reg.register(_manifest("compose", "compose.scale", "scale"), FakePlugin("a"))
    with pytest.raises(ValueError, match="different manifest"):
        reg.register(_manifest("compose", "compose.scale", "other"), FakePlugin("b"))


def test_duplicate_instance_key_is_rejected():
    reg = PluginRegistry()
    reg.register(_manifest("compose", "compose.scale", "scale"), FakePlugin("a"), key="k")
    with pytest.raises(ValueError, match="Duplicate plugin instance key"):
        reg.register(_manifest("compose", "compose.scale", "scale"), FakePlugin("b"), key="k")


def test_shared_provider_serves_any_tenant():
    reg = PluginRegistry()
    reg.register(
        _manifest("shared", "issue.read", "read"),
        FakePlugin("shared", tenant="", binding="target-x"),
    )
    assert reg.resolve("issue.read", tenant="tenant-z", binding="target-x").tag == "shared"


def test_exact_tenant_wins_over_shared():
    reg = PluginRegistry()
    reg.register(
        _manifest("shared", "issue.read", "read", priority=99),
        FakePlugin("shared", tenant="", binding="b"),
    )
    reg.register(
        _manifest("exact", "issue.read", "read", priority=1),
        FakePlugin("exact", tenant="t", binding="b"),
    )
    assert reg.resolve("issue.read", tenant="t", binding="b").tag == "exact"


def test_get_by_manifest_name_when_unique():
    reg = PluginRegistry()
    reg.register(_manifest("compose", "compose.scale", "scale"), FakePlugin("a"))
    assert reg.get("compose").tag == "a"
