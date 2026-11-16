# tests/test_integration/test_plugin_tenancy.py
"""插件启停的两层:平台提供 × 租户启用。

四件必须成立的事:

1. 租户关掉之后,那个租户解析不到它,别的租户照旧;
2. 租户不能把平台关掉的插件打开(409 说清楚,不是 403 含糊);
3. 写库带租户——一个租户点开关不会改到全局;
4. 停用但会话还在时,那张"闸门"要显式收口(见 test_console_agent 里的用例)。
"""

from __future__ import annotations

import asyncio
import textwrap
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

PLUGIN_PY = """
from engine.plugin_manager.base import PluginBase


class Demo(PluginBase):

    async def on_startup(self):
        pass

    async def on_shutdown(self):
        pass

    async def health_check(self):
        return True

    async def handle_event(self, event, data):
        return {}

    async def execute_task(self, task, params):
        return {"task": task}
"""


def _write_plugin(root, name="demo", *, default_enabled=True):
    pkg = root / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "plugin.py").write_text(textwrap.dedent(PLUGIN_PY), encoding="utf-8")
    (pkg / "plugin.yaml").write_text(
        f"name: {name}\nversion: 1.0.0\ntype: action\ndescription: d\n"
        f"class_name: Demo\ncapabilities:\n  - {name}.read\n"
        + ("" if default_enabled else "default_enabled: false\n"),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 注册表:两层取交集
# ---------------------------------------------------------------------------


def test_a_tenant_that_turned_it_off_cannot_resolve_it_but_others_can(tmp_path, monkeypatch):
    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    _write_plugin(tmp_path, "demo")

    from engine.plugin_manager.registry import PluginRegistry

    reg = PluginRegistry()
    assert reg.discover(builtin_dir=tmp_path) == 1
    reg.set_tenancy({"acme": {"demo": False}})

    # acme 关了:解析不到,报错里点名是"被这个租户关掉了"
    with pytest.raises(LookupError) as exc:
        reg.resolve("demo.read", tenant="acme")
    assert "acme" in str(exc.value)
    # 别的租户不受影响
    assert reg.resolve("demo.read", tenant="other") is not None
    # 控制面(空租户)也不受租户决定影响
    assert reg.resolve("demo.read", tenant="") is not None


def test_no_row_means_follow_the_platform_default():
    """没存过 = 没选过,不是关掉。压成 false 之后页面上就再也开不回去了。"""
    from engine.plugin_manager.registry import PluginRegistry

    reg = PluginRegistry()
    reg.set_tenancy({"acme": {"other": False}})
    assert reg.tenant_enabled("demo", "acme") is True
    assert reg.tenant_enabled("demo", "nobody") is True


def test_states_show_both_layers(tmp_path, monkeypatch):
    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    _write_plugin(tmp_path, "off-by-default", default_enabled=False)
    _write_plugin(tmp_path, "plain")

    from engine.plugin_manager.registry import PluginRegistry

    reg = PluginRegistry()
    reg.discover(builtin_dir=tmp_path)
    reg.set_tenancy({"acme": {"plain": False}})

    states = {s.manifest.name: s for s in reg.states(tenant="acme")}
    # 注意插件名别用 `on` / `off` / `yes` / `no`:YAML 1.1 会把它们读成布尔
    # 平台没提供:即使租户没关它,enabled 也是假
    assert states["off-by-default"].platform_available is False
    assert states["off-by-default"].tenant_enabled is True
    assert states["off-by-default"].enabled is False
    # 平台提供、租户关掉:两层要分开说得出
    assert states["plain"].platform_available is True
    assert states["plain"].tenant_enabled is False
    assert states["plain"].enabled is False
    assert "租户 acme 关掉了它" in states["plain"].reason


# ---------------------------------------------------------------------------
# 接口:租户不能开平台没提供的插件;开关写的是租户自己的决定
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    from engine.api.app import app
    from engine.api.routes import plugins as routes
    from engine.plugin_manager.registry import PluginRegistry

    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    _write_plugin(tmp_path, "always-off", default_enabled=False)
    _write_plugin(tmp_path, "normal")

    reg = PluginRegistry()
    reg.discover(builtin_dir=tmp_path)
    monkeypatch.setattr(routes, "registry", reg)

    # 租户级写入落文件后端,不碰部署里的库
    from engine.shared.config import config

    monkeypatch.setattr(config.settings, "change_ledger_backend", "file")
    monkeypatch.setattr(config.settings, "change_ledger_path", str(tmp_path / "ledger.jsonl"))

    return SimpleNamespace(
        app=TestClient(app), registry=reg, monkeypatch=monkeypatch, root=tmp_path
    )


def test_a_tenant_cannot_turn_on_what_the_platform_does_not_offer(client):
    resp = client.app.post("/api/plugins/always-off/enable")
    assert resp.status_code == 409
    body = resp.json()["detail"]
    assert "没有提供" in body


def test_the_switch_writes_the_tenant_decision_not_the_global_one(client):
    tenant = client.app.get("/api/plugins").json()[0]
    assert tenant  # 只要有插件清单,JWT 关掉鉴权时不带租户也能列出来

    resp = client.app.post("/api/plugins/normal/disable")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tenant_enabled"] is False
    assert body["enabled"] is False
    # 全局决定没被改:平台仍然提供它。
    # 注意 `disable` 会摘掉实例,所以此时清单已不在 `_manifests` 里——
    # `platform_available` 才是"平台提供不提供"的唯一事实来源。
    assert client.registry.decisions() == {}
    # 租户决定进了注册表,立刻影响解析
    assert client.registry.tenant_enabled("normal", "") is False
    # 平台那一层没被碰:再打开一次仍然是"平台提供的"
    reopened = client.app.post("/api/plugins/normal/enable").json()
    assert reopened["platform_available"] is True
    assert reopened["tenant_enabled"] is True


def test_the_decision_is_persisted_per_tenant(client):
    from engine.plugin_manager import tenancy

    client.app.post("/api/plugins/normal/disable")
    assert asyncio.run(tenancy.load_tenancy("")) == {"normal": False}
    # 别的租户读不到这条
    assert asyncio.run(tenancy.load_tenancy("someone-else")) == {}


def test_turning_it_back_on_keeps_the_row_explicit(client):
    client.app.post("/api/plugins/normal/disable")
    client.app.post("/api/plugins/normal/enable")

    from engine.plugin_manager import tenancy

    assert asyncio.run(tenancy.load_tenancy("")) == {"normal": True}
    listed = {p["name"]: p for p in client.app.get("/api/plugins").json()}
    assert listed["normal"]["enabled"] is True


def test_listing_carries_both_layers(client):
    listed = {p["name"]: p for p in client.app.get("/api/plugins").json()}
    assert listed["normal"]["platform_available"] is True
    assert listed["normal"]["tenant_enabled"] is True
    assert listed["always-off"]["platform_available"] is False
    assert listed["always-off"]["enabled"] is False


# ---------------------------------------------------------------------------
# 助手浮窗:关掉插件 = 浮窗消失 + 循环没有提供者
# ---------------------------------------------------------------------------


def test_the_console_dock_is_a_plugin_not_a_hardcoded_component():
    """助手窗口挂在内置插件的 `global.dock` 槽上。

    判据:在真实 builtin 目录里发现到的清单中,有且只有一个插件声明了
    `global.dock`,它同时提供 `console.chat`。这条挡住"又在布局里写死一个组件"
    这种回退。
    """
    from engine.plugin_manager import registry as real_registry

    if not real_registry.names():
        real_registry.discover()
    dock_owners = [
        state
        for state in real_registry.states()
        for widget in state.manifest.ui_widgets
        if widget.slot == "global.dock"
    ]
    assert len(dock_owners) == 1
    owner = dock_owners[0].manifest
    assert owner.name == "console-agent"
    assert "console.chat" in owner.capabilities


def test_turning_the_console_plugin_off_leaves_no_dock_and_no_loop(tmp_path, monkeypatch):
    """关掉 console-agent:槽里没有卡片,构造 agent 时如实说"没有提供者"。"""
    import asyncio as aio

    from engine.agent.provider import AgentUnavailable, build_agent
    from engine.plugin_manager import registry as real_registry

    # 真实 builtin 目录:要验的正是那一个内置插件的开关行为
    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    if not real_registry.names():
        real_registry.discover()

    state = next(s for s in real_registry.states() if s.manifest.name == "console-agent")
    assert state.enabled is True

    aio.run(real_registry.disable("console-agent"))
    try:
        # 能力没了:解析不到
        with pytest.raises(LookupError):
            real_registry.resolve("console.chat")
        # 构造 agent 的地方说的是"没有提供者、该开哪个插件",不是抛一个 None 的
        # AttributeError
        with pytest.raises(AgentUnavailable) as exc:
            build_agent(session=object(), registry=real_registry)
        assert "console-agent" in str(exc.value)
        # 槽里没有卡片:`/api/plugins/widgets` 只取 enabled 的清单,这里按同一条
        # 判据核一遍——清单还在 `available()` 里(发现 ≠ 启用),但它不该被渲染
        assert not [
            widget
            for s in real_registry.states()
            if s.enabled
            for widget in s.manifest.ui_widgets
            if widget.slot == "global.dock"
        ]
    finally:
        aio.run(real_registry.enable("console-agent"))
