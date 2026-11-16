# tests/test_integration/test_mcp_api_key.py
"""一把密钥接上 /mcp:工具按它的权限暴露,吊销之后立刻认不出。

端到端那一层只关心三件事:清单是它的,调用被它的权限拦住,吊销即失效。
密钥的存取细节在 test_api_keys 里。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.auth import keys as key_store
from engine.change_unit import JsonlLedger, Window
from engine.plugin_manager.manifest import EffectDecl
from engine.shared.config import config

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
        return {"compose.scale": {"label": DECL.label, "args": list(DECL.execute_args)}}

    def effect_decl(self, capability, tenant="", binding=""):
        return self.provider, DECL

    async def run_capability(self, capability, params):
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
    # 只配一把静态令牌,让"配了凭据就要认身份"这条生效;密钥走库里的那一套
    app.middleware("http")(make_middleware(load_tokens("t-static:acme:旁人:read")))

    return SimpleNamespace(client=TestClient(app), stub=stub, monkeypatch=monkeypatch)


def _issue(**kwargs) -> str:
    _, plaintext = asyncio.run(
        key_store.create_key(tenant="acme", **{**{"name": "agent"}, **kwargs})
    )
    return plaintext


def _rpc(client, method: str, params: dict | None = None, *, token: str, msg_id=1):
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}},
        headers={"X-Gwei-Token": token},
    )


def _text(response) -> dict:
    return json.loads(response.json()["result"]["content"][0]["text"])


# ---------------------------------------------------------------------------


def test_a_key_is_a_credential(env):
    key = _issue(permissions=["changes.read"])
    body = env.client.get("/mcp", headers={"X-Gwei-Token": key}).json()

    assert body["identity"]["name"] == "agent"
    assert body["identity"]["tenant"] == "acme"


def test_the_tool_list_is_what_the_key_can_reach(env):
    reader = _issue(name="reader", permissions=["changes.read"])
    operator = _issue(name="operator", permissions=["changes.read", "changes.execute"])

    read_tools = [t["name"] for t in _rpc(env.client, "tools/list", token=reader).json()["result"]["tools"]]
    operate_tools = [t["name"] for t in _rpc(env.client, "tools/list", token=operator).json()["result"]["tools"]]

    assert read_tools == ["changes.read"]
    assert set(operate_tools) == {"changes.read", "compose.scale"}


def test_a_key_without_the_permission_cannot_call_the_tool(env):
    reader = _issue(permissions=["changes.read"])
    body = _text(
        _rpc(
            env.client,
            "tools/call",
            {"name": "compose.scale", "arguments": {"service": "web"}},
            token=reader,
        )
    )

    assert body["ok"] is False
    assert "changes.execute" in body["reason"]
    assert env.stub.provider.executed == 0


def test_a_key_with_the_permission_goes_through_the_gate(env):
    operator = _issue(permissions=["changes.read", "changes.execute"])
    body = _text(
        _rpc(
            env.client,
            "tools/call",
            {"name": "compose.scale", "arguments": {"service": "web", "replicas": 2}},
            token=operator,
        )
    )

    assert body["ok"] is True
    assert body["verdict"] == "kept"
    assert env.stub.provider.executed == 1


def test_a_key_is_scoped_to_its_own_tenant(env):
    reader = _issue(permissions=["changes.read"])
    _rpc(env.client, "tools/call", {"name": "changes.read", "arguments": {}}, token=reader)

    # 令牌声明的租户盖过调用方自报的:密钥只能读自己那一份
    assert env.stub.reads[0][1]["tenant"] == "acme"


def test_the_whitelist_can_take_a_tool_away(env):
    """权限够但白名单只点了别的:清单里就没有它。"""
    narrow = _issue(
        name="narrow",
        permissions=["changes.read", "changes.execute"],
        tools=["changes.read"],
    )
    names = [t["name"] for t in _rpc(env.client, "tools/list", token=narrow).json()["result"]["tools"]]

    assert names == ["changes.read"]


def test_a_revoked_key_is_refused_at_the_door(env):
    key = _issue(permissions=["changes.read"])
    record = asyncio.run(key_store.list_keys("acme"))[0]
    asyncio.run(key_store.revoke_key("acme", record.id))

    resp = env.client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"X-Gwei-Token": key},
    )

    assert resp.status_code == 401


def test_a_key_shaped_string_that_is_not_a_key_is_refused(env):
    """认不出的 gwei_ 前缀不能落到"没配凭据就不鉴权"那一侧。"""
    resp = env.client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"X-Gwei-Token": key_store.KEY_PREFIX + "made-up"},
    )
    assert resp.status_code == 401
