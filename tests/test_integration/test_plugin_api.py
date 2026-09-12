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
