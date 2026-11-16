# tests/test_integration/test_plugin_api.py
"""插件清单 API 测试 —— 使用真实 builtin 目录发现(无需数据库)。"""

import pytest
from fastapi.testclient import TestClient


def _client() -> TestClient:
    from engine.api.app import app
    from engine.plugin_manager import registry

    if not registry.names():
        registry.discover()
    return TestClient(app)


def test_list_plugins_contains_builtin_agents():
    client = _client()
    resp = client.get("/api/plugins")
    assert resp.status_code == 200

    plugins = {p["name"]: p for p in resp.json()}
    assert "sensor-agent" in plugins
    assert "github-app-adapter" in plugins
    assert plugins["sensor-agent"]["capabilities"], "能力清单不应为空"


def test_widgets_slot_query_returns_observer_demo():
    client = _client()
    resp = client.get("/api/plugins/widgets", params={"slot": "issue-board.bento"})
    assert resp.status_code == 200

    widgets = resp.json()
    observer_widgets = [w for w in widgets if w["plugin"] == "observer-agent"]
    assert observer_widgets, "observer 的演示 widget 应出现在 issue-board.bento 槽位"
    assert observer_widgets[0]["kind"] == "metric"
    assert observer_widgets[0]["metrics"]


def test_widgets_unknown_slot_returns_empty():
    """查询一个不存在的槽位:没有卡片,不是错误。

    槽位名写错在**清单加载期**就被拒(见下一条),所以走到这里的只可能是调用方
    写了个还不存在的槽——返回空,让页面照常渲染。
    """
    client = _client()
    resp = client.get("/api/plugins/widgets", params={"slot": "no.such.slot"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_slot_catalogue_is_owned_by_core():
    from engine.plugin_manager.slots import SLOTS

    assert "issue-board.bento" in SLOTS


def test_widget_slot_must_be_declared_by_core(tmp_path):
    """插件不能自己开洞:写一个没人渲染的槽位,加载期就拒。"""
    from engine.plugin_manager.manifest import Manifest, ManifestError

    path = tmp_path / "plugin.yaml"
    path.write_text(
        "name: bad-slot\n"
        "version: 1.0.0\n"
        "type: dashboard_component\n"
        "description: x\n"
        "class_name: X\n"
        "ui:\n"
        "  widgets:\n"
        "    - slot: nobody.renders.this\n"
        "      kind: metric\n"
        "      title: t\n"
        "      metrics: []\n",
        encoding="utf-8",
    )

    with pytest.raises(ManifestError) as exc:
        Manifest.from_yaml(path)
    assert "槽位" in str(exc.value)


def test_plugin_manifest_exposes_observer_page():
    client = _client()
    plugins = {p["name"]: p for p in client.get("/api/plugins").json()}
    observer = plugins["observer-agent"]
    assert observer["pages"] == [{"title": "观测采样", "entry": "index.html"}]


def test_plugin_ui_asset_served():
    client = _client()
    resp = client.get("/api/plugins/observer-agent/ui/index.html")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "观测采样" in resp.text


def test_plugin_ui_path_traversal_rejected():
    client = _client()
    for evil in (
        "/api/plugins/observer-agent/ui/..%2f..%2fplugin.yaml",
        "/api/plugins/observer-agent/ui/../plugin.yaml",
        "/api/plugins/observer-agent/ui/%2e%2e/plugin.yaml",
    ):
        resp = client.get(evil)
        assert resp.status_code == 404, evil


def test_plugin_ui_unknown_plugin_404():
    client = _client()
    resp = client.get("/api/plugins/no-such-plugin/ui/index.html")
    assert resp.status_code == 404


def test_metrics_endpoint_snapshot():
    from engine.shared.metrics import metrics as collector

    collector.increment("gwei_test_probe_total", {"k": "v"})
    client = _client()
    resp = client.get("/api/metrics", params={"prefix": "gwei_test_probe_total"})
    assert resp.status_code == 200
    rows = resp.json()
    assert any(r["name"] == "gwei_test_probe_total" for r in rows)


def test_widget_live_metric_fills_value():
    from engine.shared.metrics import metrics as collector

    collector.increment("gwei_llm_calls_total")
    client = _client()
    resp = client.get("/api/plugins/widgets", params={"slot": "issue-board.bento"})
    widgets = [w for w in resp.json() if w["plugin"] == "observer-agent"]
    assert widgets, "observer widget 缺失"
    llm = next(m for m in widgets[0]["metrics"] if m["label"] == "LLM 调用")
    assert llm["value"] >= 1, "widget 应填充收集器实时值"

# ---------------------------------------------------------------------------
# 发现 ≠ 启用:GET /api/plugins 要把该差别说出来,并且能改
# ---------------------------------------------------------------------------


def test_list_includes_disabled_plugins_with_reason():
    """未启用的插件也在列表里,`enabled` 说它此刻在不在流程里。"""
    client = _client()
    rows = {p["name"]: p for p in client.get("/api/plugins").json()}

    # 清单里 default_enabled: false 的 cnb/gitlab/alertmanager 适配器必须出现,且 enabled 为假
    for name in ("cnb-adapter", "gitlab-adapter", "alertmanager-adapter"):
        assert name in rows, f"{name} 在清单里,却没在列表里——页面上就没法把它打开"
        assert rows[name]["enabled"] is False
        assert "default_enabled" in rows[name]["reason"]

    assert rows["sensor-agent"]["enabled"] is True
    assert rows["sensor-agent"]["instances"] == ["sensor-agent"]


def test_widgets_only_come_from_enabled_plugins():
    """卡片要拿得到数:未启用插件的卡片不该出现在插槽里。"""
    from engine.plugin_manager import registry

    client = _client()
    widgets = client.get(
        "/api/plugins/widgets", params={"slot": "issue-board.bento"}
    ).json()
    assert any(w["plugin"] == "observer-agent" for w in widgets)

    state = _state_of(registry, "observer-agent")
    if state is None or not state.enabled:
        return

    import asyncio

    asyncio.run(registry.disable("observer-agent"))
    try:
        widgets = client.get(
            "/api/plugins/widgets", params={"slot": "issue-board.bento"}
        ).json()
        assert not any(w["plugin"] == "observer-agent" for w in widgets)
    finally:
        asyncio.run(registry.enable("observer-agent"))


def _state_of(registry, name):
    for state in registry.states():
        if state.manifest.name == name:
            return state
    return None


def test_ui_asset_requires_plugins_read_when_auth_is_on(monkeypatch):
    """同一组接口不能有两种权限口径:资产端点也要 require。"""
    from engine.api import auth as auth_mod

    monkeypatch.setattr(auth_mod, "_AUTH_STATE", {"required": True})
    client = _client()
    resp = client.get("/api/plugins/observer-agent/ui/index.html")
    assert resp.status_code == 401


def test_enable_unknown_plugin_404():
    client = _client()
    resp = client.post("/api/plugins/no-such-plugin/enable")
    assert resp.status_code == 404
    assert "no-such-plugin" in resp.json()["detail"]
