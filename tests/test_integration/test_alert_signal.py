# tests/test_integration/test_alert_signal.py
"""第二个信号源:监控告警走同一条链路,但没有人替它编动作。"""

from __future__ import annotations

import asyncio
import importlib

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


# ---------------------------------------------------------------------------
# 告警声明动作:平台只翻译,不猜
# ---------------------------------------------------------------------------


def _alert_signal(**annotations):
    return {
        "source": "alertmanager",
        "subject": "api-gateway",
        "title": "内存占用过高",
        "detail": "RSS 超过 2GiB",
        "severity": "critical",
        "ref": "abc123",
        "labels": {"alertname": "HighMemory"},
        "annotations": annotations,
    }


def test_alert_declaration_becomes_one_effect():
    import json as _json

    from engine.change_unit.intent import parse_intent

    plugin_mod = importlib.import_module("plugins.builtin.agents.intent-builder.plugin")
    alerts_mod = importlib.import_module("plugins.builtin.agents.intent-builder.alerts")

    signal = _alert_signal(
        gwei_effect=_json.dumps(
            {"capability": "compose.scale", "args": {"service": "api", "replicas": 10}}
        )
    )
    effect = alerts_mod.declared_effect(signal)
    assert effect == {
        "capability": "compose.scale",
        "args": {"service": "api", "replicas": 10},
    }

    intent = asyncio.run(plugin_mod.IntentBuilder().propose({"signal": signal}))
    parsed = parse_intent(intent.to_dict())
    assert len(parsed.effects) == 1
    assert parsed.effects[0]["capability"] == "compose.scale"


def test_broken_declaration_is_treated_as_absent():
    alerts_mod = importlib.import_module("plugins.builtin.agents.intent-builder.alerts")
    assert alerts_mod.declared_effect(_alert_signal(gwei_effect="{not json")) is None
    assert alerts_mod.declared_effect(_alert_signal(gwei_effect='{"args": {}}')) is None
    assert alerts_mod.declared_effect(_alert_signal()) is None


def test_alert_without_declaration_yields_empty_effects():
    alerts_mod = importlib.import_module("plugins.builtin.agents.intent-builder.alerts")
    intent = alerts_mod.intent_from_alert(_alert_signal())
    assert intent["effects"] == []
    assert "没有声明动作" in intent["summary"]


def test_intent_naming_an_unknown_capability_blocks_instead_of_crashing(tmp_path, monkeypatch):
    """告警声明的动作没人提供时,记成阻断,不让整个工作流崩。"""
    from engine.workflows import pipeline

    monkeypatch.setattr(pipeline.config.settings, "change_ledger_backend", "file")
    monkeypatch.setattr(
        pipeline.config.settings, "change_ledger_path", str(tmp_path / "l.jsonl")
    )

    def no_provider(*args, **kwargs):
        raise LookupError("no provider declares effect: compose.scale")

    monkeypatch.setattr(pipeline.registry, "effect_decl", no_provider)

    intent = {
        "version": 1,
        "summary": "针对 api-gateway 执行 compose.scale",
        "evidence": [],
        "effects": [{"capability": "compose.scale", "args": {"service": "api"}}],
        "rationale": "r",
    }
    out = asyncio.run(
        pipeline._apply_effects_impl(intent, {"tenant_slug": "default"}, "wf-alert:effects")
    )
    assert out["applied"][0]["verdict"] == "blocked"
    assert "没有提供者" in out["applied"][0]["reason"]


# ---------------------------------------------------------------------------
# 端到端:告警声明 → 信号 → intent → 变更单元 → 账本
# ---------------------------------------------------------------------------


class _ComposeProvider:
    binding = "local"
    tenant = ""

    def __init__(self):
        self.executed = 0

    async def window(self, effect, handle):
        from engine.change_unit import Window

        return Window(unbounded=True, source="project_present")

    async def execute(self, task, args):
        self.executed += 1
        return {"handle": "compose-1"}

    async def undo(self, task, args, handle):
        return {}

    async def verify(self, effect, handle):
        return True, {"running_replicas": 10}


def test_alert_declaration_becomes_a_change_unit_in_the_ledger(tmp_path, monkeypatch):
    """一条告警声明执行 compose.scale,走完 intent → 效果 → 账本,落成一条可撤的单元。"""
    import json as _json

    from engine.change_unit import JsonlLedger
    from engine.plugin_manager.manifest import EffectDecl

    plugin_mod = importlib.import_module("plugins.builtin.agents.intent-builder.plugin")
    builder = plugin_mod.IntentBuilder()

    async def run_capability(capability, params):
        if capability != "intent.propose":
            raise LookupError(capability)
        return (await builder.propose(params)).to_dict()

    provider = _ComposeProvider()
    decl = EffectDecl(
        capability="compose.scale",
        execute_task="scale",
        undo_task="undo_scale",
        undo_kind="symmetric",
        window_read="project_present",
        verify=({"query": "running_replicas", "expect": ">= 10"},),
    )

    ledger_path = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(pipeline.registry, "run_capability", run_capability)
    monkeypatch.setattr(
        pipeline.registry, "effect_decl", lambda *a, **k: (provider, decl)
    )
    monkeypatch.setattr(pipeline.config.settings, "change_ledger_backend", "file")
    monkeypatch.setattr(pipeline.config.settings, "change_ledger_path", str(ledger_path))
    monkeypatch.setattr(pipeline.config.settings, "default_binding", "local")

    payload = {
        "tenant_slug": "default",
        "signal": _alert_signal(
            gwei_effect=_json.dumps(
                {
                    "capability": "compose.scale",
                    "args": {"project_dir": "/srv/api", "service": "api", "replicas": 10},
                }
            )
        ),
    }

    intent = asyncio.run(pipeline._propose_intent_impl(payload, {}, []))
    out = asyncio.run(pipeline._apply_effects_impl(intent, payload, "wf-alert:effects"))

    assert provider.executed == 1
    assert out["applied"][0]["verdict"] == "kept"

    rows = asyncio.run(JsonlLedger(ledger_path).read())
    assert len(rows) == 1
    assert rows[0]["verdict"] == "kept"
    assert rows[0]["binding"] == "local"
    assert rows[0]["effect"]["capability"] == "compose.scale"
    assert rows[0]["window"]["unbounded"] is True


def test_payload_signal_is_used_verbatim():
    signal = {"source": "alertmanager", "subject": "api-gateway", "title": "x", "detail": ""}
    assert pipeline.signal_from_payload({"signal": signal}) is signal
