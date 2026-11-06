# tests/test_integration/test_settings_persistence.py
"""配置值存进业务库:填一次活过重启,harness 的凭据由平台注入而不是进容器手配。"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from pydantic import BaseModel, Field
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
    assert asyncio.run(again.load()) == {
        "": {"harness-env": {"deepseek_api_key": "sk-1"}}
    }


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
    fields = {f["name"]: f for f in rows["demo-bot"]["fields"]}

    assert fields["base_url"]["set"] is True
    assert rows["demo-bot"]["missing"] == ["DEMO_BOT_API_KEY"]
    assert "harness-env" in rows


def test_a_secret_is_never_echoed_by_default(client):
    client.put("/api/settings/scopes/harness-env", json={"values": {"deepseek_api_key": "sk-x"}})
    rows = {row["name"]: row for row in client.get("/api/settings/scopes").json()}
    fields = {f["name"]: f for f in rows["harness-env"]["fields"]}

    assert fields["deepseek_api_key"]["set"] is True
    assert fields["deepseek_api_key"]["value"] is None


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

# ---------------------------------------------------------------------------
# 回显策略:每个字段自己说了算
# ---------------------------------------------------------------------------


class DemoBotSettings(BaseModel):
    api_key: str = Field(..., json_schema_extra={"expose": "masked"})
    base_url: str = Field("", json_schema_extra={"expose": "always"})
    owner_token: str = Field(
        "", json_schema_extra={"expose": "always", "read_scope": "operate"}
    )
    private_key: str = Field("", json_schema_extra={"expose": "never"})
    retries: int = 3


@pytest.fixture
def model_scope(store):
    config.register_model_scope("demo-model", DemoBotSettings, prefix="DEMO_MODEL_")
    return "demo-model"


@pytest.fixture
def client_model(model_scope):
    app = FastAPI()
    app.include_router(scopes_mod.router)
    return TestClient(app)


@pytest.fixture
def read_client(model_scope):
    from engine.api.auth import load_tokens, make_middleware

    app = FastAPI()
    app.include_router(scopes_mod.router)
    app.middleware("http")(make_middleware(load_tokens("t-view:acme:只读:read")))
    return TestClient(app)


def _fields(client, token: str | None = None) -> dict:
    headers = {"X-Gwei-Token": token} if token else {}
    rows = {
        row["name"]: row
        for row in client.get("/api/settings/scopes", headers=headers).json()
    }
    return {field["name"]: field for field in rows["demo-model"]["fields"]}


def test_masked_shows_enough_to_recognise_it(client_model):
    client_model.put(
        "/api/settings/scopes/demo-model",
        json={"values": {"api_key": "sk-abcdef123456", "base_url": "https://x"}},
    )
    fields = _fields(client_model)
    assert fields["api_key"]["value"] == "sk-a…3456"
    assert fields["base_url"]["value"] == "https://x"


def test_a_never_field_is_only_reported_as_set(client_model):
    client_model.put(
        "/api/settings/scopes/demo-model",
        json={"values": {"api_key": "k-1234567890", "private_key": "-----BEGIN"}},
    )
    fields = _fields(client_model)
    assert fields["private_key"]["set"] is True
    assert fields["private_key"]["value"] is None


def test_an_operate_field_is_hidden_from_a_read_token(client_model, read_client):
    client_model.put(
        "/api/settings/scopes/demo-model",
        json={"values": {"api_key": "k-1234567890", "owner_token": "own-1"}},
    )

    seen_by_reader = _fields(read_client, "t-view")
    assert seen_by_reader["owner_token"]["set"] is True
    assert seen_by_reader["owner_token"]["value"] is None
    # 同一个字段,运维视角看得到
    assert _fields(client_model)["owner_token"]["value"] == "own-1"


def test_a_wrong_shape_is_refused_before_it_is_stored(client_model):
    resp = client_model.put(
        "/api/settings/scopes/demo-model", json={"values": {"retries": "abc"}}
    )
    assert resp.status_code == 422


def test_half_filled_is_not_an_error(client_model):
    """缺必填由 missing 报,不该拦住先填一半。"""
    resp = client_model.put(
        "/api/settings/scopes/demo-model", json={"values": {"base_url": "https://y"}}
    )
    assert resp.status_code == 200, resp.text
    assert "DEMO_MODEL_API_KEY" in resp.json()["missing"]

# ---------------------------------------------------------------------------
# 租户:先读公共,再读自己的
# ---------------------------------------------------------------------------


def test_a_tenant_value_overrides_the_public_one(store, scopes):
    asyncio.run(store.put("demo-bot", {"api_key": "public"}))
    asyncio.run(store.put("demo-bot", {"api_key": "acme"}, tenant="acme"))
    config.apply_stored(asyncio.run(store.load()))

    assert config.get_scope_config("demo-bot")["api_key"] == "public"
    assert config.get_scope_config("demo-bot", tenant="acme")["api_key"] == "acme"
    # 没设过的租户落回公共值,不是落空
    assert config.get_scope_config("demo-bot", tenant="other")["api_key"] == "public"


def test_a_tenant_only_value_does_not_leak(store, scopes):
    asyncio.run(store.put("demo-bot", {"api_key": "acme-only"}, tenant="acme"))
    config.apply_stored(asyncio.run(store.load()))

    assert config.get_scope_config("demo-bot", tenant="other") == {}
    assert config.validate_scope("demo-bot", tenant="other") == ["DEMO_BOT_API_KEY"]


def test_the_harness_env_is_per_tenant(store, scopes):
    asyncio.run(store.put("harness-env", {"deepseek_api_key": "public"}))
    asyncio.run(store.put("harness-env", {"deepseek_api_key": "acme"}, tenant="acme"))
    config.apply_stored(asyncio.run(store.load()))

    assert build_env(tenant="acme")["DEEPSEEK_API_KEY"] == "acme"
    assert build_env()["DEEPSEEK_API_KEY"] == "public"


def test_the_api_writes_into_the_callers_tenant(model_scope):
    from engine.api.auth import load_tokens, make_middleware

    app = FastAPI()
    app.include_router(scopes_mod.router)
    app.middleware("http")(make_middleware(load_tokens("t-a:acme:值班:operate")))
    client = TestClient(app)

    client.put(
        "/api/settings/scopes/demo-model",
        json={"values": {"api_key": "k-acme-1234"}},
        headers={"X-Gwei-Token": "t-a"},
    )
    assert config.get_scope_config("demo-model", tenant="acme")["api_key"] == "k-acme-1234"
    assert "api_key" not in config.get_scope_config("demo-model")

# ---------------------------------------------------------------------------
# 删:删掉租户的那一份,读的时候落回公共值
# ---------------------------------------------------------------------------


def test_deleting_a_tenant_value_falls_back_to_the_public_one(store, scopes):
    asyncio.run(store.put("demo-bot", {"api_key": "public"}))
    asyncio.run(store.put("demo-bot", {"api_key": "acme"}, tenant="acme"))
    config.apply_stored(asyncio.run(store.load()))
    assert config.get_scope_config("demo-bot", tenant="acme")["api_key"] == "acme"

    assert asyncio.run(store.delete("demo-bot", "api_key", tenant="acme")) is True
    config.apply_stored(asyncio.run(store.load()))

    assert config.get_scope_config("demo-bot", tenant="acme")["api_key"] == "public"


def test_deleting_a_key_that_is_not_there_reports_false(store, scopes):
    assert asyncio.run(store.delete("demo-bot", "nope")) is False


def test_the_api_deletes_a_value_and_says_what_is_left(client):
    client.put("/api/settings/scopes/demo-bot", json={"values": {"base_url": "https://x"}})
    resp = client.delete("/api/settings/scopes/demo-bot/base_url")
    assert resp.status_code == 200, resp.text
    assert resp.json()["set"] == []
    assert config.get_scope_config("demo-bot") == {}


def test_the_api_says_404_for_a_missing_key_or_scope(client):
    assert client.delete("/api/settings/scopes/demo-bot/nope").status_code == 404
    assert client.delete("/api/settings/scopes/nope/key").status_code == 404


def test_the_api_deletes_only_inside_the_callers_tenant(model_scope):
    from engine.api.auth import load_tokens, make_middleware

    app = FastAPI()
    app.include_router(scopes_mod.router)
    app.middleware(
        "http"
    )(make_middleware(load_tokens("t-a:acme:值班:operate,t-r:*:维护者:operate")))
    client = TestClient(app)
    headers_a = {"X-Gwei-Token": "t-a"}
    headers_root = {"X-Gwei-Token": "t-r"}

    client.put("/api/settings/scopes/demo-model", json={"values": {"base_url": "public"}}, headers=headers_root)
    client.put("/api/settings/scopes/demo-model", json={"values": {"base_url": "acme"}}, headers=headers_a)
    config.apply_stored(asyncio.run(create_settings_store().load()))

    # acme 删自己的那一份,公共值不动
    assert client.delete("/api/settings/scopes/demo-model/base_url", headers=headers_a).status_code == 200
    config.apply_stored(asyncio.run(create_settings_store().load()))
    assert config.get_scope_config("demo-model")["base_url"] == "public"
    assert config.get_scope_config("demo-model", tenant="acme")["base_url"] == "public"
