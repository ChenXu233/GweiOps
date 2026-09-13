# tests/test_integration/test_plugin_api.py
"""插件清单 API 测试 —— 使用真实 builtin 目录发现(无需数据库)。"""

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
    resp = client.get("/api/plugins/widgets", params={"slot": "dashboard.bento"})
    assert resp.status_code == 200

    widgets = resp.json()
    observer_widgets = [w for w in widgets if w["plugin"] == "observer-agent"]
    assert observer_widgets, "observer 的演示 widget 应出现在 dashboard.bento 槽位"
    assert observer_widgets[0]["kind"] == "metric"
    assert observer_widgets[0]["metrics"]


def test_widgets_unknown_slot_returns_empty():
    client = _client()
    resp = client.get("/api/plugins/widgets", params={"slot": "no.such.slot"})
    assert resp.status_code == 200
    assert resp.json() == []


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
