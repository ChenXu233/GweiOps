# tests/test_integration/test_settings_persistence.py
"""配置值存进业务库:填一次活过重启,harness 的凭据由平台注入而不是进容器手配。"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.api.routes import settings_scopes as scopes_mod
from engine.harness import build_env
from engine.shared.config import config
from engine.shared.settings_store import JsonlSettingsStore, create_settings_store


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "change_ledger_backend", "file")
    monkeypatch.setattr(
        config.settings, "change_ledger_path", str(tmp_path / "ledger.jsonl")
    )
    saved = config.all_stored()
    monitor = create_settings_store()
    assert isinstance(monitor, JsonlSettingsStore)
    yield monitor
    config.apply_stored(saved)


@pytest.fixture
def scopes(store):
    config.register_scope(
        name="demo-bot", prefix="DEMO_BOT_", required=["api_key"], optional=["base_url"]
    )
    return store


# ---------------------------------------------------------------------------
# 存与读
# ---------------------------------------------------------------------------


def test_a_value_survives_a_restart(store):
    asyncio.run(store.put("harness-env", {"deepseek_api_key": "sk-1"}))
    # 换一个实例读,证明它是落在文件里而不是内存里
    again = create_settings_store()
    assert asyncio.run(again.load()) == {"harness-env": {"deepseek_api_key": "sk-1"}}


def test_stored_beats_the_environment(monkeypatch, scopes):
    monkeypatch.setenv("DEMO_BOT_API_KEY", "from-env")
    asyncio.run(scopes.put("demo-bot", {"api_key": "from-db"}))
    config.apply_stored(asyncio.run(scopes.load()))

    assert config.get_scope_config("demo-bot")["api_key"] == "from-db"
    assert config.validate_scope("demo-bot") == []


def test_a_free_form_scope_returns_whatever_was_stored(scopes):
    """harness-env 不预设字段名:存什么就是什么,键名由用的人决定。"""
    asyncio.run(scopes.put("harness-env", {"deepseek_api_key": "sk-2", "dsH_MODEL": "m"}))
    config.apply_stored(asyncio.run(scopes.load()))

    assert config.get_scope_config("harness-env") == {
        "deepseek_api_key": "sk-2",
        "dsH_MODEL": "m",
    }


def test_the_missing_list_still_points_at_a_env_name(scopes):
    assert config.validate_scope("demo-bot") == ["DEMO_BOT_API_KEY"]


# ---------------------------------------------------------------------------
# 注入:凭据进容器,由平台给
# ---------------------------------------------------------------------------


def test_the_harness_gets_the_stored_credentials_as_upper_case_env(scopes):
    asyncio.run(scopes.put("harness-env", {"deepseek_api_key": "sk-3"}))
    config.apply_stored(asyncio.run(scopes.load()))

    env = build_env({"GWEI_EXIT_URL": "http://gw"})
    assert env["DEEPSEEK_API_KEY"] == "sk-3"
    assert env["GWEI_EXIT_URL"] == "http://gw"


# ---------------------------------------------------------------------------
# 接口:看得到要填什么,看不到填了什么
# ---------------------------------------------------------------------------


@pytest.fixture
def client(scopes):
    app = FastAPI()
    app.include_router(scopes_mod.router)
    return TestClient(app)


def test_putting_a_value_never_echoes_it(client):
    resp = client.put(
        "/api/settings/scopes/harness-env", json={"values": {"deepseek_api_key": "sk-secret"}}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["set"] == ["deepseek_api_key"]
    assert "sk-secret" not in resp.text


def test_listing_shows_what_is_set_and_what_is_missing(client):
    client.put("/api/settings/scopes/demo-bot", json={"values": {"base_url": "https://x"}})
    rows = {row["name"]: row for row in client.get("/api/settings/scopes").json()}

    assert rows["demo-bot"]["set"] == ["base_url"]
    assert rows["demo-bot"]["missing"] == ["DEMO_BOT_API_KEY"]
    assert "harness-env" in rows


def test_an_unknown_scope_is_404(client):
    assert (
        client.put("/api/settings/scopes/nope", json={"values": {"a": "b"}}).status_code
        == 404
    )


def test_an_empty_write_is_refused(client):
    assert client.put("/api/settings/scopes/demo-bot", json={"values": {}}).status_code == 400


def test_a_written_value_is_immediately_live(client):
    client.put("/api/settings/scopes/demo-bot", json={"values": {"api_key": "sk-live"}})
    assert config.get_scope_config("demo-bot")["api_key"] == "sk-live"
    assert config.validate_scope("demo-bot") == []
