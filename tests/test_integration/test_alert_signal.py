# tests/test_integration/test_alert_signal.py
"""第二个信号源:监控告警走同一条链路,但没有人替它编动作。"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI

from engine.api.routes import webhook as webhook_mod
from engine.ingest import SignalError, from_github, parse_alerts
from engine.shared.config import config
from engine.workflows import pipeline

TOKEN = "test-token"


def _alert(**overrides):
    alert = {
        "status": "firing",
        "labels": {
            "alertname": "HighMemory",
            "severity": "critical",
            "service": "api-gateway",
        },
        "annotations": {"summary": "内存占用过高", "description": "RSS 超过 2GiB"},
        "startsAt": "2026-11-04T22:00:00Z",
        "fingerprint": "abc123",
    }
    alert.update(overrides)
    return alert


# ---------------------------------------------------------------------------
# 归化
# ---------------------------------------------------------------------------


def test_alertmanager_payload_becomes_signals():
    signals = parse_alerts({"alerts": [_alert()]})
    assert len(signals) == 1

    signal = signals[0]
    assert signal["source"] == "alertmanager"
    assert signal["subject"] == "api-gateway"
    assert signal["title"] == "内存占用过高"
    assert signal["severity"] == "critical"
    assert signal["ref"] == "abc123"
    assert signal["started_at"] == "2026-11-04T22:00:00Z"


def test_resolved_alerts_are_not_signals():
    """resolved 说的是"事情过去了",不是"哪里出了事"。"""
    assert parse_alerts({"alerts": [_alert(status="resolved")]}) == []


def test_duplicate_fingerprints_collapse():
    assert len(parse_alerts({"alerts": [_alert(), _alert()]})) == 1


def test_severity_and_title_fallbacks():
    signal = parse_alerts(
        {"alerts": [_alert(labels={"alertname": "DiskFull", "severity": "warning"}, annotations={})]}
    )[0]
    assert signal["severity"] == "medium"
    assert signal["subject"] == "DiskFull"
    assert signal["title"] == "DiskFull"


def test_alert_without_any_name_is_skipped():
    assert parse_alerts({"alerts": [_alert(labels={}, annotations={})]}) == []


def test_github_payload_keeps_the_handle_for_commenting():
    signal = from_github(
        {
            "repo_full_name": "ChenXu233/GweiOps",
            "issue_number": 3,
            "title": "空指针崩溃",
            "body": "打开页面就崩",
        }
    )
    assert signal["source"] == "github"
    assert signal["subject"] == "ChenXu233/GweiOps#3"
    assert signal["detail"] == "打开页面就崩"
    assert signal["repo"] == "ChenXu233/GweiOps"
    assert signal["issue_number"] == 3


def test_malformed_github_payload_raises():
    with pytest.raises(SignalError):
        from_github({"title": "没有仓库和 issue 号"})


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def _post(payload: dict, headers: dict | None = None):
    async def run():
        app = FastAPI()
        app.include_router(webhook_mod.router)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/webhook/alertmanager", json=payload, headers=headers or {})

    return asyncio.run(run())


def test_rejects_when_no_token_is_configured(monkeypatch):
    monkeypatch.setattr(config.settings, "alertmanager_webhook_token", "")
    assert _post({"alerts": []}).status_code == 503


def test_rejects_a_bad_token(monkeypatch):
    monkeypatch.setattr(config.settings, "alertmanager_webhook_token", TOKEN)
    assert _post({"alerts": []}, {"X-Gwei-Token": "nope"}).status_code == 401


def test_ignores_a_payload_without_firing_alerts(monkeypatch):
    monkeypatch.setattr(config.settings, "alertmanager_webhook_token", TOKEN)
    resp = _post({"alerts": [_alert(status="resolved")]}, {"X-Gwei-Token": TOKEN})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_enqueues_one_workflow_per_alert(monkeypatch):
    monkeypatch.setattr(config.settings, "alertmanager_webhook_token", TOKEN)
    calls: list[tuple] = []

    async def fake_enqueue(queue, workflow, payload):
        calls.append((queue, workflow.__name__, payload))

    async def first_time(key, ttl):
        return True

    monkeypatch.setattr(webhook_mod.DBOS, "enqueue_workflow_async", fake_enqueue)
    monkeypatch.setattr(webhook_mod, "dedup_once", first_time)

    resp = _post(
        {"alerts": [_alert(), _alert(fingerprint="def456")]}, {"X-Gwei-Token": TOKEN}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 2
    assert [call[1] for call in calls] == ["alert_triage_workflow", "alert_triage_workflow"]
    assert calls[0][2]["signal"]["source"] == "alertmanager"
    assert calls[0][2]["tenant_slug"] == config.settings.default_tenant_slug


def test_a_repeated_delivery_is_deduped(monkeypatch):
    monkeypatch.setattr(config.settings, "alertmanager_webhook_token", TOKEN)

    async def already_seen(key, ttl):
        return False

    monkeypatch.setattr(webhook_mod, "dedup_once", already_seen)
    resp = _post({"alerts": [_alert()]}, {"X-Gwei-Token": TOKEN})
    assert resp.status_code == 200
    assert resp.json()["status"] == "duplicate"


# ---------------------------------------------------------------------------
# 链路:没有提供者就不编动作
# ---------------------------------------------------------------------------


def test_alert_signal_without_a_provider_produces_no_effect(monkeypatch):
    """以前这里会 KeyError(repo_full_name):监控信号根本没有仓库。"""

    async def no_provider(capability, params):
        raise LookupError(capability)

    monkeypatch.setattr(pipeline.registry, "run_capability", no_provider)

    intent = asyncio.run(
        pipeline._propose_intent_impl(
            {
                "tenant_slug": "default",
                "signal": {
                    "source": "alertmanager",
                    "subject": "api-gateway",
                    "title": "内存占用过高",
                    "detail": "RSS 超过 2GiB",
                },
            },
            {},
            [],
        )
    )
    assert intent["effects"] == []
    assert "没有可执行的意图" in intent["summary"]
    assert intent["evidence"][0]["kind"] == "alertmanager"


def test_payload_signal_is_used_verbatim():
    signal = {"source": "alertmanager", "subject": "api-gateway", "title": "x", "detail": ""}
    assert pipeline.signal_from_payload({"signal": signal}) is signal
