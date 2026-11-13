# tests/test_integration/test_agent_exit_api.py
"""出口端点:沙箱里的 agent 隔着网络改世界,过的是同一条闸门。"""

from __future__ import annotations

import asyncio
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
    binding = "github"  # 与 settings.default_binding 一致,免得每个用例都要写 binding
    tenant = ""

    def __init__(self, *, pre: Window | None = None) -> None:
        self.pre = pre or Window(unbounded=True, source="fake")
        self.executed = 0

    async def window(self, effect, handle):
        return self.pre

    async def execute(self, task, args):
        self.executed += 1
        return {"handle": "h-1"}

    async def undo(self, task, args, handle):
        return {}

    async def verify(self, effect, handle):
        return True, {"running_replicas": 3}


class Registry:
    def __init__(self, *, provider=None, menu=None) -> None:
        self.provider = provider if provider is not None else Provider()
        self.menu = MENU if menu is None else menu
        self.reads: list[tuple[str, dict]] = []

    def declared_effects(self):
        return self.menu

    def effect_decl(self, capability, tenant="", binding=""):
        if self.provider is None:
            raise LookupError(f"nobody declares {capability}")
        return self.provider, DECL

    async def run_capability(self, capability, params):
        if capability != "issue.read":
            raise LookupError(f"no provider for {capability}")
        self.reads.append((capability, params))
        return {"ok": True}

    def names(self):
        return ["fake"]

    def manifest(self, name):
        return SimpleNamespace(capabilities=["issue.read"])


@pytest.fixture
def env(tmp_path, monkeypatch):
    """一个配了令牌、账本落在临时文件、出口被替身接管的 app。"""
    from engine.api.auth import load_tokens, make_middleware
    from engine.api.routes import agent as agent_mod

    monkeypatch.setattr(config.settings, "change_ledger_backend", "file")
    monkeypatch.setattr(
        config.settings, "change_ledger_path", str(tmp_path / "ledger.jsonl")
    )
    stub = Registry()
    monkeypatch.setattr(agent_mod, "registry", stub)

    app = FastAPI()
    app.include_router(agent_mod.router)
    app.middleware("http")(make_middleware(load_tokens(f"{OPERATOR},{VIEWER}")))

    ledger = JsonlLedger(config.settings.change_ledger_path)
    return SimpleNamespace(
        client=TestClient(app),
        stub=stub,
        ledger=ledger,
        provider=stub.provider,
        monkeypatch=monkeypatch,
    )


def _h(token: str = "t-operate") -> dict:
    return {"X-Gwei-Token": token}


def _rows(ledger: JsonlLedger) -> list[dict]:
    return asyncio.run(ledger.latest())


# ---------------------------------------------------------------------------


def test_the_exit_list_needs_a_token(env):
    assert env.client.get("/api/agent/exits").status_code == 401


def test_the_exit_list_is_the_menu(env):
    body = env.client.get("/api/agent/exits", headers=_h()).json()
    names = [spec["function"]["name"] for spec in body["tools"]]
    assert names == ["compose.scale", "issue.read"]


def test_a_read_only_token_cannot_use_the_exits(env):
    resp = env.client.post(
        "/api/agent/exits/compose.scale",
        json={"args": {"service": "web"}},
        headers=_h("t-read"),
    )
    assert resp.status_code == 403


def test_an_exit_call_becomes_a_change_unit(env):
    resp = env.client.post(
        "/api/agent/exits/compose.scale",
        json={"args": {"service": "web", "replicas": 3}, "summary": "错误率上升"},
        headers=_h(),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["verdict"] == "kept"

    rows = _rows(env.ledger)
    assert len(rows) == 1
    assert rows[0]["binding"] == "github"
    assert rows[0]["tenant"] == "acme"
    assert rows[0]["intent"]["by"] == "值班人"
    assert rows[0]["intent"]["via"] == "exit"


def test_a_read_exit_leaves_the_ledger_alone(env):
    resp = env.client.post(
        "/api/agent/exits/issue.read", json={"args": {"repo": "o/r"}}, headers=_h()
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert env.stub.reads == [("issue.read", {"repo": "o/r"})]
    assert _rows(env.ledger) == []


def test_an_unknown_exit_is_a_result_not_a_500(env):
    resp = env.client.post("/api/agent/exits/nope.read", json={}, headers=_h())
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert "没有这个出口" in resp.json()["reason"]


def test_another_binding_is_refused_not_executed(env):
    """跨环境执行是事故:单元记在 staging,提供者只服务 github,必须被拒。"""
    resp = env.client.post(
        "/api/agent/exits/compose.scale",
        json={"args": {"service": "web"}, "binding": "staging"},
        headers=_h(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is False
    assert "binding" in resp.json()["reason"]
    assert env.provider.executed == 0
    # 绑错了是配置错误,不是一次结论:没有动过外部世界,也就不该在账本里留一行
    assert _rows(env.ledger) == []


def test_a_repeated_call_id_replays_instead_of_acting_twice(env):
    payload = {"args": {"service": "web", "replicas": 2}, "call_id": "c-1"}
    first = env.client.post("/api/agent/exits/compose.scale", json=payload, headers=_h())
    second = env.client.post("/api/agent/exits/compose.scale", json=payload, headers=_h())

    assert first.status_code == second.status_code == 200
    assert env.provider.executed == 1
    assert second.json()["verdict"] == "kept"


def test_the_hourly_cap_stops_a_runaway_agent(env):
    env.monkeypatch.setattr(config.settings, "agent_max_exits_per_hour", 1)
    first = env.client.post(
        "/api/agent/exits/compose.scale",
        json={"args": {"service": "web", "replicas": 2}, "call_id": "c-1"},
        headers=_h(),
    )
    assert first.status_code == 200

    second = env.client.post(
        "/api/agent/exits/compose.scale",
        json={"args": {"service": "web", "replicas": 3}, "call_id": "c-2"},
        headers=_h(),
    )
    assert second.status_code == 429
    assert "上限" in second.json()["detail"]


def test_reads_do_not_consume_the_budget(env):
    env.monkeypatch.setattr(config.settings, "agent_max_exits_per_hour", 1)
    env.client.post(
        "/api/agent/exits/compose.scale",
        json={"args": {"service": "web", "replicas": 2}},
        headers=_h(),
    )
    resp = env.client.post("/api/agent/exits/issue.read", json={}, headers=_h())
    assert resp.status_code == 200

def test_the_incident_id_travels_with_the_call(env):
    env.client.post(
        "/api/agent/exits/compose.scale",
        json={"args": {"service": "web", "replicas": 2}, "incident_id": "inc-7"},
        headers=_h(),
    )
    assert _rows(env.ledger)[0]["incident_id"] == "inc-7"


def test_the_same_call_id_in_another_incident_is_another_change(env):
    """call_id 只在一次事故里有意义:换一次事故,同样的编号就是另一件事。"""
    payload = {"args": {"service": "web", "replicas": 2}, "call_id": "c-1"}
    env.client.post(
        "/api/agent/exits/compose.scale",
        json={**payload, "incident_id": "inc-1"},
        headers=_h(),
    )
    env.client.post(
        "/api/agent/exits/compose.scale",
        json={**payload, "incident_id": "inc-2"},
        headers=_h(),
    )
    assert env.provider.executed == 2
    assert len(_rows(env.ledger)) == 2

# ---------------------------------------------------------------------------
# 出口读工作区:files 不用 agent 手填
# ---------------------------------------------------------------------------

PR_DECL = EffectDecl(
    capability="pr.open",
    execute_task="open_pull",
    undo_task="close_pull",
    undo_kind="symmetric",
    window_read="pull_open",
    verify=({"query": "pull_open", "expect": "true"},),
    label="开一个 PR",
    execute_args=("repo", "head", "title", "files", "paths"),
)


class PrProvider(Provider):
    def __init__(self) -> None:
        super().__init__()
        self.args: dict | None = None

    async def execute(self, task, args):
        self.executed += 1
        self.args = dict(args)
        return {"handle": "1", "url": "https://github.com/o/r/pull/1"}


def _pr_app(tmp_path, monkeypatch, provider):
    from engine.api.auth import load_tokens, make_middleware
    from engine.api.routes import agent as agent_mod

    monkeypatch.setattr(config.settings, "change_ledger_backend", "file")
    monkeypatch.setattr(
        config.settings, "change_ledger_path", str(tmp_path / "ledger.jsonl")
    )

    class PrRegistry(Registry):
        def __init__(self) -> None:
            super().__init__(provider=provider)
            self.menu = {
                "pr.open": {"label": PR_DECL.label, "args": list(PR_DECL.execute_args)}
            }

        def effect_decl(self, capability, tenant="", binding=""):
            return provider, PR_DECL

    stub = PrRegistry()
    monkeypatch.setattr(agent_mod, "registry", stub)

    app = FastAPI()
    app.include_router(agent_mod.router)
    app.middleware("http")(make_middleware(load_tokens(OPERATOR)))
    return SimpleNamespace(
        client=TestClient(app), stub=stub, provider=provider, module=agent_mod
    )


def test_the_exit_fills_files_from_the_workspace(tmp_path, monkeypatch):
    """agent 说"我改了这些路径",内容由平台去工作区读——别让它把整份文件塞进参数。"""
    provider = PrProvider()
    env = _pr_app(tmp_path, monkeypatch, provider)
    seen = {}

    async def fake_files(incident_id, paths):
        seen["incident_id"] = incident_id
        seen["paths"] = paths
        return [{"path": "engine/x.py", "content": "x = 1\n"}]

    monkeypatch.setattr(env.module, "_workspace_files", fake_files)

    resp = env.client.post(
        "/api/agent/exits/pr.open",
        json={
            "args": {"repo": "o/r", "head": "gwei/x", "paths": ["engine/x.py"]},
            "incident_id": "inc-1",
        },
        headers=_h(),
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    assert seen == {"incident_id": "inc-1", "paths": ["engine/x.py"]}
    assert provider.args["files"] == [{"path": "engine/x.py", "content": "x = 1\n"}]
    # paths 只是"读哪几个"的简写,不该跟着效果进账本
    assert "paths" not in provider.args


def test_arguments_may_sit_at_the_top_level(tmp_path, monkeypatch):
    """出口清单是"这个动作要哪些参数",照它把参数写在外层是最自然的读法。"""
    provider = PrProvider()
    env = _pr_app(tmp_path, monkeypatch, provider)

    async def fake_files(incident_id, paths):
        return [{"path": "README.md", "content": "x\n"}]

    monkeypatch.setattr(env.module, "_workspace_files", fake_files)

    resp = env.client.post(
        "/api/agent/exits/pr.open",
        json={
            "repo": "o/r",
            "head": "gwei/x",
            "title": "加一节",
            "incident_id": "inc-1",
        },
        headers=_h(),
    )

    assert resp.status_code == 200, resp.text
    assert provider.args["repo"] == "o/r"
    assert provider.args["head"] == "gwei/x"
    assert provider.args["title"] == "加一节"
    assert provider.args["files"] == [{"path": "README.md", "content": "x\n"}]


def test_a_workspace_that_cannot_be_read_stops_before_the_call(tmp_path, monkeypatch):
    from engine.harness.workspace import WorkspaceError

    provider = PrProvider()
    env = _pr_app(tmp_path, monkeypatch, provider)

    async def fake_files(incident_id, paths):
        raise WorkspaceError("这一场没有仓库副本,读不出改动")

    monkeypatch.setattr(env.module, "_workspace_files", fake_files)

    resp = env.client.post(
        "/api/agent/exits/pr.open",
        json={"args": {"repo": "o/r", "head": "gwei/x"}, "incident_id": "inc-1"},
        headers=_h(),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "读不出工作区的改动" in body["reason"]
    assert provider.executed == 0, "读不出改动就不该去开 PR"
