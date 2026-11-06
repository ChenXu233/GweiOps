# tests/test_integration/test_incidents.py
"""事故报告:开始写一行,收尾改写同一行;开着没收口本身就是信息。"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.api.routes import incidents as incidents_mod
from engine.incidents import JsonlIncidentStore, create_incident_store
from engine.shared.config import config
from engine.workflows import pipeline

SIGNAL = {"source": "alertmanager", "subject": "high-error", "title": "错误率超过 10%"}
REPORT = {
    "source": "agent",
    "summary": "加了两个副本,错误率回落",
    "counts": {"kept": 1, "blocked": 1},
    "steps": [{"tool": "compose.scale", "result": {"verdict": "kept"}}],
    "exhausted": False,
}


@pytest.fixture
def store(tmp_path, monkeypatch) -> JsonlIncidentStore:
    monkeypatch.setattr(config.settings, "change_ledger_backend", "file")
    monkeypatch.setattr(
        config.settings, "change_ledger_path", str(tmp_path / "ledger.jsonl")
    )
    made = create_incident_store()
    assert isinstance(made, JsonlIncidentStore)
    return made


def _opened(store, incident_id="inc-1", tenant="acme"):
    return asyncio.run(
        store.open(incident_id=incident_id, tenant=tenant, signal=SIGNAL)
    )


# ---------------------------------------------------------------------------


def test_an_incident_starts_open(store):
    row = _opened(store)
    assert row["status"] == "open"
    assert row["signal_title"] == SIGNAL["title"]
    assert row["finished_at"] == ""


def test_closing_writes_the_report(store):
    _opened(store)
    closed = asyncio.run(store.close("inc-1", report=REPORT))

    assert closed["status"] == "closed"
    assert closed["summary"] == REPORT["summary"]
    assert closed["counts"] == {"kept": 1, "blocked": 1}
    assert closed["finished_at"]
    assert asyncio.run(store.get("inc-1"))["status"] == "closed"


def test_closing_an_incident_that_never_opened_is_a_no_op(store):
    assert asyncio.run(store.close("nope", report=REPORT)) is None


def test_an_open_incident_is_visible_as_open(store):
    """开了没收口 = 那一场卡住了,不是"什么都没发生"。"""
    _opened(store, "inc-1")
    _opened(store, "inc-2")
    asyncio.run(store.close("inc-2", report=REPORT))

    rows = {row["id"]: row for row in asyncio.run(store.list())}
    assert rows["inc-1"]["status"] == "open"
    assert rows["inc-2"]["status"] == "closed"


def test_listing_is_scoped_by_tenant_and_newest_first(store):
    asyncio.run(
        store.open(
            incident_id="old",
            tenant="acme",
            signal=SIGNAL,
            started_at="2026-11-06T01:00:00+00:00",
        )
    )
    asyncio.run(
        store.open(
            incident_id="new",
            tenant="acme",
            signal=SIGNAL,
            started_at="2026-11-06T02:00:00+00:00",
        )
    )
    _opened(store, "other", tenant="other")

    rows = asyncio.run(store.list(tenant="acme"))
    assert [row["id"] for row in rows] == ["new", "old"]


def test_get_respects_the_tenant(store):
    _opened(store, "inc-1", tenant="acme")
    assert asyncio.run(store.get("inc-1", tenant="other")) is None


# ---------------------------------------------------------------------------
# 工作流:开始与收尾各是一个 step
# ---------------------------------------------------------------------------


class FakeDBOS:
    workflow_id = "wf-1"


@pytest.fixture
def workflow(store, monkeypatch):
    monkeypatch.setattr(pipeline, "DBOS", FakeDBOS)
    return store


def test_the_workflow_opens_then_closes_the_incident(workflow):
    payload = {"signal": dict(SIGNAL), "tenant_slug": "acme"}

    opened = asyncio.run(pipeline._open_incident_impl(payload))
    assert opened["id"] == "wf-1"
    assert opened["status"] == "open"

    asyncio.run(pipeline._close_incident_impl(payload, {**REPORT, "source": "operator"}))
    row = asyncio.run(workflow.get("wf-1"))
    assert row["status"] == "closed"
    assert row["source"] == "operator"
    assert row["tenant"] == "acme"


def test_the_declarative_path_still_produces_a_report(workflow):
    report = pipeline.declarative_report(
        {"summary": "针对某 issue 给出回评"},
        {
            "applied": [
                {"capability": "comment.create", "verdict": "kept", "reason": "验证通过"},
                {"capability": "compose.scale", "verdict": "blocked", "reason": "窗口读不到"},
            ]
        },
    )
    assert report["source"] == "declarative"
    assert report["counts"] == {"kept": 1, "blocked": 1}
    assert [step["tool"] for step in report["steps"]] == ["comment.create", "compose.scale"]
    assert report["exhausted"] is False


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.fixture
def client(store):
    app = FastAPI()
    app.include_router(incidents_mod.router)
    return TestClient(app)


def test_api_lists_and_returns_an_incident(client):
    asyncio.run(
        create_incident_store().open(incident_id="inc-1", tenant="acme", signal=SIGNAL)
    )

    listing = client.get("/api/incidents").json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == "inc-1"

    detail = client.get("/api/incidents/inc-1").json()
    assert detail["signal_title"] == SIGNAL["title"]


def test_api_returns_404_for_an_unknown_incident(client):
    assert client.get("/api/incidents/nope").status_code == 404
