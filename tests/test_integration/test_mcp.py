# tests/test_integration/test_mcp.py
"""MCP:别人的 agent 通过一个端点用这台机器。

这件事的关键不是协议,是它没有另开一套权限与账本:tools/list 就是出口清单,
tools/call 就是出口调用,落的是同一行账。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.change_unit import JsonlLedger, Window
from engine.plugin_manager.manifest import EffectDecl
from engine.shared.config import config

OPERATOR = "t-operate:acme:值班人:operate"
VIEWER = "t-read:acme:只读:read"

DECL = EffectDecl(
    capability="compose.scale",
    execute_task="scale",
    undo_task="undo_scale",
    undo_kind="symmetric",
    window_read="project_present",
    verify=({"query": "running_replicas", "expect": ">= 1"},),
    label="调整 compose 服务副本数",
    execute_args=("project_dir", "service", "replicas"),
)

MENU = {"compose.scale": {"label": DECL.label, "args": list(DECL.execute_args)}}


class Provider:
    binding = "github"
    tenant = ""

    def __init__(self) -> None:
        self.executed = 0

    async def window(self, effect, handle):
        return Window(unbounded=True, source="fake")

    async def execute(self, task, args):
        self.executed += 1
        return {"handle": "h-1"}

    async def undo(self, task, args, handle):
        return {}

    async def verify(self, effect, handle):
        return True, {"running_replicas": 3}


class Registry:
    def __init__(self) -> None:
        self.provider = Provider()
        self.reads: list[tuple[str, dict]] = []

    def declared_effects(self):
        return MENU

    def effect_decl(self, capability, tenant="", binding=""):
        return self.provider, DECL

    async def run_capability(self, capability, params):
        if capability != "changes.read":
            raise LookupError(f"no provider for {capability}")
        self.reads.append((capability, params))
        return {"items": [], "count": 0}

    def names(self):
        return ["fake"]

    def manifest(self, name):
        return SimpleNamespace(capabilities=["changes.read"])


@pytest.fixture
def env(tmp_path, monkeypatch):
    from engine.api.auth import load_tokens, make_middleware
    from engine.api.routes import mcp as mcp_mod

    monkeypatch.setattr(config.settings, "change_ledger_backend", "file")
    monkeypatch.setattr(config.settings, "change_ledger_path", str(tmp_path / "ledger.jsonl"))
    stub = Registry()
    monkeypatch.setattr(mcp_mod, "registry", stub)

    app = FastAPI()
    app.include_router(mcp_mod.router)
    app.middleware("http")(make_middleware(load_tokens(f"{OPERATOR},{VIEWER}")))

    return SimpleNamespace(
        client=TestClient(app),
        stub=stub,
        ledger=JsonlLedger(config.settings.change_ledger_path),
        monkeypatch=monkeypatch,
    )


def _h(token: str = "t-operate") -> dict:
    return {"X-Gwei-Token": token}


def _rpc(client, method: str, params: dict | None = None, *, token: str = "t-operate", msg_id=1):
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}},
        headers=_h(token),
    )


def _text(response) -> dict:
    body = response.json()["result"]
    return json.loads(body["content"][0]["text"])


# ---------------------------------------------------------------------------


def test_it_needs_a_token(env):
    resp = env.client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert resp.status_code == 401


def test_initialize_says_who_it_is(env):
    body = _rpc(env.client, "initialize").json()["result"]

    assert body["protocolVersion"]
    assert body["serverInfo"]["name"] == "gweiops"
    assert "tools" in body["capabilities"]
    assert "出口" in body["instructions"]


def test_the_tool_list_is_the_exit_menu(env):
    tools = _rpc(env.client, "tools/list").json()["result"]["tools"]
    names = [tool["name"] for tool in tools]

    assert "compose.scale" in names
    assert "changes.read" in names
    scale = next(tool for tool in tools if tool["name"] == "compose.scale")
    assert scale["description"].startswith(DECL.label)
    assert "service" in scale["inputSchema"]["properties"]


def test_a_call_becomes_a_change_unit(env):
    body = _text(
        _rpc(
            env.client,
            "tools/call",
            {"name": "compose.scale", "arguments": {"service": "web", "replicas": 2}},
        )
    )

    assert body["ok"] is True
    assert body["verdict"] == "kept"
    assert env.stub.provider.executed == 1

    rows = asyncio.run(env.ledger.latest())
    assert len(rows) == 1
    assert rows[0]["intent"]["by"] == "值班人"


def test_a_read_tool_does_not_write_a_ledger_row(env):
    body = _text(
        _rpc(env.client, "tools/call", {"name": "changes.read", "arguments": {"limit": 5}})
    )

    assert body["ok"] is True
    assert env.stub.reads[0][0] == "changes.read"
    assert asyncio.run(env.ledger.latest()) == []


def test_a_read_tool_is_scoped_to_the_callers_tenant(env):
    _rpc(env.client, "tools/call", {"name": "changes.read", "arguments": {}})

    # 令牌声明的租户盖过调用方自报的,查询范围才收得住
    assert env.stub.reads[0][1]["tenant"] == "acme"


def test_a_read_only_identity_cannot_use_an_effect(env):
    response = _rpc(
        env.client,
        "tools/call",
        {"name": "compose.scale", "arguments": {"service": "web"}},
        token="t-read",
    )
    body = response.json()["result"]

    assert body["isError"] is True
    assert "只读" in json.loads(body["content"][0]["text"])["reason"]
    assert env.stub.provider.executed == 0


def test_an_unknown_tool_comes_back_as_a_result_not_a_crash(env):
    body = _text(_rpc(env.client, "tools/call", {"name": "nope.read", "arguments": {}}))

    assert body["ok"] is False
    assert "没有这个出口" in body["reason"]


def test_notifications_are_accepted_without_a_body(env):
    resp = env.client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=_h(),
    )
    assert resp.status_code == 202


def test_an_unknown_method_is_a_jsonrpc_error(env):
    assert _rpc(env.client, "tools/nope").json()["error"]["code"] == -32601


def test_get_says_what_this_endpoint_is(env):
    body = env.client.get("/mcp", headers=_h()).json()

    assert body["transport"] == "streamable-http"
    assert "compose.scale" in body["tools"]
