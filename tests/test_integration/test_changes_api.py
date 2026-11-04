# tests/test_integration/test_changes_api.py
"""账本 API:折叠当前状态、拒绝重复撤销、撤销本身也留痕。"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.api.routes import changes as changes_mod
from engine.change_unit import ChangeUnit, Effect, JsonlLedger, Window
from engine.plugin_manager.manifest import EffectDecl
from engine.shared.config import config

DECL = EffectDecl(
    capability="comment.create",
    execute_task="create_comment",
    undo_task="delete_comment",
    undo_kind="symmetric",
    window_read="comment_present",
    verify=({"query": "comment_exists", "expect": "true"},),
)


class FakeProvider:
    binding = "github"
    tenant = ""

    def __init__(self):
        self.undone: list[str] = []

    async def undo(self, task, args, handle):
        self.undone.append(handle)
        return {}

    async def window(self, effect, handle):
        raise AssertionError("回滚不该读窗口")

    async def verify(self, effect, handle):
        return True, {}

    async def execute(self, task, args):
        raise AssertionError("回滚不该执行")


def _unit(verdict="kept", handle="42", unit_id="u1"):
    return ChangeUnit(
        id=unit_id,
        intent={"summary": "回评"},
        effect=Effect(
            task="create_comment",
            args={"repo": "o/r", "issue_number": 1, "body": "hi"},
            undo_task="delete_comment",
            undo_kind="symmetric",
            capability="comment.create",
        ),
        tenant="",
        binding="github",
        handle=handle,
        verdict=verdict,
        reason="验证通过",
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "change_ledger_backend", "file")
    monkeypatch.setattr(config.settings, "change_ledger_path", str(tmp_path / "ledger.jsonl"))
    app = FastAPI()
    app.include_router(changes_mod.router)
    return TestClient(app)


@pytest.fixture
def ledger(client):
    return JsonlLedger(config.settings.change_ledger_path)


def test_empty_ledger(client):
    body = client.get("/api/changes").json()
    assert body == {"items": [], "total": 0}


def test_latest_folds_events(client, ledger):
    asyncio.run(ledger.append(_unit("kept")))
    asyncio.run(ledger.append(_unit("rolled_back")))
    body = client.get("/api/changes").json()
    assert body["total"] == 1
    assert body["items"][0]["verdict"] == "rolled_back"


def test_history_returns_all_events(client, ledger):
    asyncio.run(ledger.append(_unit("kept")))
    asyncio.run(ledger.append(_unit("rolled_back")))
    body = client.get("/api/changes/u1").json()
    assert len(body["history"]) == 2
    assert body["latest"]["verdict"] == "rolled_back"


def test_unknown_change_404(client):
    assert client.get("/api/changes/nope").status_code == 404
    assert client.post("/api/changes/nope/rollback").status_code == 404


def test_rollback_applies_and_appends_audit_row(client, ledger, monkeypatch):
    asyncio.run(ledger.append(_unit("kept")))
    provider = FakeProvider()
    monkeypatch.setattr(
        changes_mod.registry, "effect_decl", lambda *a, **k: (provider, DECL)
    )

    resp = client.post("/api/changes/u1/rollback?reason=早上审案")
    assert resp.status_code == 200, resp.text
    assert provider.undone == ["42"]
    body = resp.json()
    assert body["latest"]["verdict"] == "rolled_back"
    assert body["latest"]["reason"] == "早上审案"
    assert len(body["history"]) == 2


def test_rollback_twice_conflicts(client, ledger, monkeypatch):
    asyncio.run(ledger.append(_unit("rolled_back")))
    monkeypatch.setattr(
        changes_mod.registry, "effect_decl", lambda *a, **k: (FakeProvider(), DECL)
    )
    assert client.post("/api/changes/u1/rollback").status_code == 409


def test_rollback_unapplied_is_bad_request(client, ledger):
    asyncio.run(ledger.append(_unit("blocked", handle=None)))
    assert client.post("/api/changes/u1/rollback").status_code == 400


def test_rollback_without_provider_is_503(client, ledger, monkeypatch):
    asyncio.run(ledger.append(_unit("kept")))

    def boom(*a, **k):
        raise LookupError("no provider")

    monkeypatch.setattr(changes_mod.registry, "effect_decl", boom)
    assert client.post("/api/changes/u1/rollback").status_code == 503


def test_filters(client, ledger):
    asyncio.run(ledger.append(_unit("kept", unit_id="a")))
    asyncio.run(ledger.append(_unit("blocked", handle=None, unit_id="b")))
    assert client.get("/api/changes?verdict=blocked").json()["total"] == 1
    assert client.get("/api/changes?binding=nope").json()["total"] == 0

# ---------------------------------------------------------------------------
# 阻断的出口:放行 / 否决
# ---------------------------------------------------------------------------


class RunProvider:
    """放行路径需要真的执行:读窗口 → 执行 → 读窗口 → 验证。"""

    binding = "github"
    tenant = ""

    def __init__(self, *, window=None):
        self.executed = 0
        self.undone = 0
        self._window = window or Window(unbounded=True, source="fake")

    async def window(self, effect, handle):
        return self._window

    async def execute(self, task, args):
        self.executed += 1
        return {"handle": "95"}

    async def undo(self, task, args, handle):
        self.undone += 1
        return {}

    async def verify(self, effect, handle):
        return True, {"comment_exists": True}


def test_approve_runs_a_blocked_unit(client, ledger, monkeypatch):
    asyncio.run(ledger.append(_unit("blocked", handle=None)))
    provider = RunProvider()
    monkeypatch.setattr(
        changes_mod.registry, "effect_decl", lambda *a, **k: (provider, DECL)
    )

    resp = client.post("/api/changes/u1/approve?by=值班人&reason=现在就做")
    assert resp.status_code == 200, resp.text
    assert provider.executed == 1

    body = resp.json()
    assert body["latest"]["verdict"] == "kept"
    assert body["latest"]["facts"]["authorized_by"] == "值班人"
    assert len(body["history"]) == 2


def test_approve_rejects_an_already_executed_unit(client, ledger):
    asyncio.run(ledger.append(_unit("kept")))
    assert client.post("/api/changes/u1/approve").status_code == 409


def test_approve_without_provider_is_503(client, ledger, monkeypatch):
    asyncio.run(ledger.append(_unit("blocked", handle=None)))

    def boom(*a, **k):
        raise LookupError("no provider")

    monkeypatch.setattr(changes_mod.registry, "effect_decl", boom)
    assert client.post("/api/changes/u1/approve").status_code == 503


def test_veto_writes_a_decision_row(client, ledger):
    asyncio.run(ledger.append(_unit("blocked", handle=None)))
    resp = client.post("/api/changes/u1/veto?by=值班人&reason=等周一")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["latest"]["verdict"] == "vetoed"
    assert body["latest"]["reason"] == "等周一"
    assert body["latest"]["facts"]["vetoed_by"] == "值班人"
    assert len(body["history"]) == 2


def test_veto_rejects_an_executed_unit(client, ledger):
    asyncio.run(ledger.append(_unit("kept")))
    assert client.post("/api/changes/u1/veto").status_code == 409


def test_veto_unknown_change_404(client):
    assert client.post("/api/changes/nope/veto").status_code == 404
