# tests/test_integration/test_changes_api.py
"""账本 API:折叠当前状态、拒绝重复撤销、撤销本身也留痕。"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.api.routes import changes as changes_mod
from engine.change_unit import ChangeUnit, Effect, JsonlLedger
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
    monkeypatch.setattr(config.settings, "change_ledger_path", str(tmp_path / "ledger.jsonl"))
    app = FastAPI()
    app.include_router(changes_mod.router)
    return TestClient(app)


@pytest.fixture
def ledger(client):
    return JsonlLedger(config.settings.change_ledger_path)


def test_empty_ledger(client):
    body = client.get("/changes").json()
    assert body == {"items": [], "total": 0}


def test_latest_folds_events(client, ledger):
    ledger.append(_unit("kept"))
    ledger.append(_unit("rolled_back"))
    body = client.get("/changes").json()
    assert body["total"] == 1
    assert body["items"][0]["verdict"] == "rolled_back"


def test_history_returns_all_events(client, ledger):
    ledger.append(_unit("kept"))
    ledger.append(_unit("rolled_back"))
    body = client.get("/changes/u1").json()
    assert len(body["history"]) == 2
    assert body["latest"]["verdict"] == "rolled_back"


def test_unknown_change_404(client):
    assert client.get("/changes/nope").status_code == 404
    assert client.post("/changes/nope/rollback").status_code == 404


def test_rollback_applies_and_appends_audit_row(client, ledger, monkeypatch):
    ledger.append(_unit("kept"))
    provider = FakeProvider()
    monkeypatch.setattr(
        changes_mod.registry, "effect_decl", lambda *a, **k: (provider, DECL)
    )

    resp = client.post("/changes/u1/rollback?reason=早上审案")
    assert resp.status_code == 200, resp.text
    assert provider.undone == ["42"]
    body = resp.json()
    assert body["latest"]["verdict"] == "rolled_back"
    assert body["latest"]["reason"] == "早上审案"
    assert len(body["history"]) == 2


def test_rollback_twice_conflicts(client, ledger, monkeypatch):
    ledger.append(_unit("rolled_back"))
    monkeypatch.setattr(
        changes_mod.registry, "effect_decl", lambda *a, **k: (FakeProvider(), DECL)
    )
    assert client.post("/changes/u1/rollback").status_code == 409


def test_rollback_unapplied_is_bad_request(client, ledger):
    ledger.append(_unit("blocked", handle=None))
    assert client.post("/changes/u1/rollback").status_code == 400


def test_rollback_without_provider_is_503(client, ledger, monkeypatch):
    ledger.append(_unit("kept"))

    def boom(*a, **k):
        raise LookupError("no provider")

    monkeypatch.setattr(changes_mod.registry, "effect_decl", boom)
    assert client.post("/changes/u1/rollback").status_code == 503


def test_filters(client, ledger):
    ledger.append(_unit("kept", unit_id="a"))
    ledger.append(_unit("blocked", handle=None, unit_id="b"))
    assert client.get("/changes?verdict=blocked").json()["total"] == 1
    assert client.get("/changes?binding=nope").json()["total"] == 0
