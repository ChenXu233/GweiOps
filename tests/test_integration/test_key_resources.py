# tests/test_integration/test_key_resources.py
"""密钥的资源维度:这把钥匙能碰哪些下游目标。

权限说"能不能改世界",资源说"能改哪一个"。两关都过才看得见工具 —— 一把只
签了 `local` 的钥匙,`github` 上的工具不在它的清单里,知道了名字也调不动。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.auth import ALL_PERMISSIONS, DEFAULT_ROLES
from engine.auth import keys as key_store
from engine.auth.keys import resource_allowed, tool_allowed, tool_visible
from engine.change_unit import Window
from engine.plugin_manager.manifest import EffectDecl
from engine.shared.config import config

OPERATOR = "t-operate:acme:值班人:operate"

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


class FakeActor:
    """与 engine.api.auth.Actor 同一个形状。"""

    def __init__(self, *, permissions=(), tools=(), bindings=(), scope="operate", static=False):
        self.permissions = frozenset(permissions)
        self.tools = frozenset(tools)
        self.bindings = frozenset(bindings)
        self.scope = scope
        self.static = static

    @property
    def scoped(self) -> bool:
        return not self.static


class Provider:
    def __init__(self, binding: str) -> None:
        self.binding = binding
        self.tenant = ""
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
    """两个目标上的同一个能力:判"只签了一个也算够得着"。"""

    def __init__(self) -> None:
        self.local = Provider("local")
        self.remote = Provider("remote")
        self.reads: list[tuple[str, dict]] = []

    def declared_effects(self):
        return {"compose.scale": {"label": DECL.label, "args": list(DECL.execute_args)}}

    def effect_decl(self, capability, tenant="", binding=""):
        return (self.local if binding == "local" else self.remote), DECL

    def tool_bindings(self, capability):
        return ("local", "remote") if capability == "compose.scale" else ()

    def resources(self):
        return ["local", "remote"]

    def resource_capabilities(self):
        return {"local": ["compose.scale"], "remote": ["compose.scale"]}

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
    from engine.api.routes import agent as agent_mod
    from engine.api.routes import mcp as mcp_mod

    monkeypatch.setattr(config.settings, "change_ledger_backend", "file")
    monkeypatch.setattr(config.settings, "change_ledger_path", str(tmp_path / "ledger.jsonl"))
    stub = Registry()
    monkeypatch.setattr(mcp_mod, "registry", stub)
    monkeypatch.setattr(agent_mod, "registry", stub)

    app = FastAPI()
    app.include_router(mcp_mod.router)
    app.include_router(agent_mod.router)
    app.middleware("http")(make_middleware(load_tokens(OPERATOR)))
    return SimpleNamespace(client=TestClient(app), stub=stub)


def _issue(**kwargs) -> str:
    _, plaintext = asyncio.run(
        key_store.create_key(tenant="acme", **{**{"name": "agent"}, **kwargs})
    )
    return plaintext


def _rpc(client, method, params=None, *, token, msg_id=1):
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}},
        headers={"X-Gwei-Token": token},
    )


# ---------------------------------------------------------------------------
# 判据
# ---------------------------------------------------------------------------


def test_an_empty_resource_list_means_unbounded():
    """老密钥没有这一栏:空 = 不限,不能因为加了资源维度就把它们全废掉。"""
    assert resource_allowed("local", FakeActor(permissions=ALL_PERMISSIONS))
    assert tool_visible("compose.scale", FakeActor(permissions=ALL_PERMISSIONS), lambda _: ("local",))


def test_a_listed_resource_is_reachable_and_others_are_not():
    actor = FakeActor(permissions=ALL_PERMISSIONS, bindings={"local"})
    assert resource_allowed("local", actor)
    assert not resource_allowed("remote", actor)


def test_a_tool_is_visible_when_any_of_its_resources_is_in_scope():
    actor = FakeActor(permissions=ALL_PERMISSIONS, bindings={"local"})
    assert tool_visible("compose.scale", actor, lambda _: ("local", "remote"))
    assert not tool_visible("compose.scale", actor, lambda _: ("remote",))


def test_a_tool_that_names_no_resource_is_not_filtered_by_resources():
    """只读口说不出自己在哪个目标上 —— 拿资源去拦它只会把账本也一起拦掉。"""
    actor = FakeActor(permissions=ALL_PERMISSIONS, bindings={"local"})
    assert tool_visible("changes.read", actor, lambda _: ())


def test_permissions_still_have_the_last_word():
    actor = FakeActor(permissions={"changes.read"}, bindings={"local"})
    assert not tool_visible("compose.scale", actor, lambda _: ("local",))


def test_a_narrower_tool_whitelist_still_applies():
    actor = FakeActor(permissions=ALL_PERMISSIONS, tools={"changes.read"}, bindings={"local"})
    assert not tool_visible("compose.scale", actor, lambda _: ("local",))


# ---------------------------------------------------------------------------
# 端到端:工具清单与调用都按资源收
# ---------------------------------------------------------------------------


def test_the_tool_list_follows_the_key_resources(env):
    local_only = _issue(permissions=["changes.read", "changes.execute"], bindings=["local"])
    tools = [
        t["name"]
        for t in _rpc(env.client, "tools/list", token=local_only).json()["result"]["tools"]
    ]
    assert "compose.scale" in tools

    nowhere = _issue(permissions=["changes.read", "changes.execute"], bindings=["elsewhere"])
    narrowed = [
        t["name"]
        for t in _rpc(env.client, "tools/list", token=nowhere).json()["result"]["tools"]
    ]
    assert narrowed == ["changes.read"]


def test_calling_a_tool_on_another_resource_is_refused(env):
    key = _issue(permissions=["changes.read", "changes.execute"], bindings=["local"])
    body = json.loads(
        _rpc(
            env.client,
            "tools/call",
            {
                "name": "compose.scale",
                "arguments": {"_binding": "remote", "service": "web", "replicas": 2},
            },
            token=key,
        ).json()["result"]["content"][0]["text"]
    )

    assert body["ok"] is False
    assert "remote" in body["reason"]
    assert env.stub.remote.executed == 0


def test_the_exit_route_uses_the_same_judgement(env):
    key = _issue(permissions=["changes.read", "changes.execute"], bindings=["local"])
    headers = {"X-Gwei-Token": key}

    listed = env.client.get("/api/agent/exits", headers=headers).json()
    assert "compose.scale" in [t["function"]["name"] for t in listed["tools"]]

    refused = env.client.post(
        "/api/agent/exits/compose.scale",
        json={"binding": "remote", "args": {"service": "web", "replicas": 2}},
        headers=headers,
    )
    assert refused.status_code == 403
    assert env.stub.remote.executed == 0


def test_the_describe_endpoint_says_what_the_key_is_scoped_to(env):
    key = _issue(permissions=["changes.read"], bindings=["local"])
    body = env.client.get("/mcp", headers={"X-Gwei-Token": key}).json()

    assert body["identity"]["resources"] == ["local"]


# ---------------------------------------------------------------------------
# 预设角色:运维能看也能操作
# ---------------------------------------------------------------------------


def test_the_operator_preset_can_issue_and_revoke_keys():
    presets = {role["key"]: set(role["permissions"]) for role in DEFAULT_ROLES}
    assert {"keys.read", "keys.manage"} <= presets["operator"]
    # 管钥不越权:运维拿不到管人、管角色
    assert not presets["operator"] & {"users.manage", "roles.manage"}


def test_the_viewer_preset_still_cannot_see_keys():
    presets = {role["key"]: set(role["permissions"]) for role in DEFAULT_ROLES}
    assert not presets["viewer"] & {"keys.read", "keys.manage"}
