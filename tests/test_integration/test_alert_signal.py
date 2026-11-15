# tests/test_integration/test_alert_signal.py
"""第二个信号源:监控告警走同一条链路,但没有人替它编动作。"""

from __future__ import annotations

import asyncio
import importlib

import httpx
import pytest
from fastapi import FastAPI

from engine.api.routes import webhook as webhook_mod
from engine.ingest import SignalError, from_github
from engine.shared.config import config
from engine.workflows import pipeline
from engine.workflows import queue as queue_mod

am_mod = importlib.import_module("plugins.builtin.adapters.alertmanager.plugin")

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
    signals = am_mod.signals_from_payload({"alerts": [_alert()]})
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
    assert am_mod.signals_from_payload({"alerts": [_alert(status="resolved")]}) == []


def test_duplicate_fingerprints_collapse():
    assert len(am_mod.signals_from_payload({"alerts": [_alert(), _alert()]})) == 1


def test_severity_and_title_fallbacks():
    signal = am_mod.signals_from_payload(
        {"alerts": [_alert(labels={"alertname": "DiskFull", "severity": "warning"}, annotations={})]}
    )[0]
    assert signal["severity"] == "medium"
    assert signal["subject"] == "DiskFull"
    assert signal["title"] == "DiskFull"


def test_alert_without_any_name_is_skipped():
    assert am_mod.signals_from_payload({"alerts": [_alert(labels={}, annotations={})]}) == []


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


class _FakeDBOS:
    """只做一件事:收下 enqueue_workflow_async 的调用。"""

    def __init__(self, enqueue):
        self.enqueue_workflow_async = enqueue


def _post(payload: dict, headers: dict | None = None, path: str = "/webhook/alertmanager"):
    async def run():
        app = FastAPI()
        app.include_router(webhook_mod.router)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(path, json=payload, headers=headers or {})

    return asyncio.run(run())


class _AdapterConfig:
    """适配器眼里只有一个令牌;入口不该从测试里读到真实环境。"""

    def __init__(self, token: str) -> None:
        self.token = token


def _adapter(token: str):
    adapter = am_mod.AlertmanagerAdapter()
    adapter.config = _AdapterConfig(token)

    async def reload_config():
        adapter.config = _AdapterConfig(token)

    # 入口在"没配密钥"时会重载一次配置;这里让它重载成同一个值,
    # 免得测试结果取决于这台机器上的环境变量。
    adapter.on_startup = reload_config
    return adapter


@pytest.fixture
def ingress(monkeypatch):
    def bind(token: str = TOKEN):
        adapter = _adapter(token)
        monkeypatch.setattr(webhook_mod, "source_adapter", lambda source: adapter)
        return adapter

    return bind


def test_rejects_when_no_token_is_configured(ingress):
    ingress("")
    assert _post({"alerts": []}).status_code == 503


def test_rejects_a_bad_token(ingress):
    ingress(TOKEN)
    assert _post({"alerts": []}, {"X-Gwei-Token": "nope"}).status_code == 401


def test_ignores_a_payload_without_firing_alerts(ingress):
    ingress(TOKEN)
    resp = _post({"alerts": [_alert(status="resolved")]}, {"X-Gwei-Token": TOKEN})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_unknown_source_is_refused(monkeypatch):
    """没装适配器就是 503:不猜一个"默认来源",那比拒绝更糟。"""
    def nobody(source):
        raise LookupError(f"没有为 {source} 配置 webhook 适配器")

    monkeypatch.setattr(webhook_mod, "source_adapter", nobody)
    resp = _post({"alerts": []}, path="/webhook/nobody")
    assert resp.status_code == 503
    assert "nobody" in resp.json()["detail"]


def test_a_new_source_needs_no_core_change(monkeypatch):
    """接一个新告警系统 = 一个声明 produces=signal 的适配器,入口一个字都不用改。"""
    calls: list[tuple] = []

    class CaddyAdapter:
        source = "caddy"
        produces = "signal"
        config_hint = "CADDY_WEBHOOK_TOKEN"

        def webhook_configured(self):
            return True

        def verify_webhook(self, headers, body):
            return True

        def parse_signals(self, headers, body):
            return [
                {
                    "source": "caddy",
                    "subject": "api.example.com",
                    "title": "证书 3 天后过期",
                    "detail": "",
                    "severity": "medium",
                    "ref": "api.example.com",
                    "occurrence": "2026-11-14",
                }
            ]

    async def fake_enqueue(queue, workflow, payload):
        calls.append((queue, workflow.__name__, payload))

    async def first_time(key, ttl):
        return True

    monkeypatch.setattr(webhook_mod, "source_adapter", lambda source: CaddyAdapter())
    # 入队的规矩在 workflows/queue.py:DBOS 在那一边,不在路由里
    monkeypatch.setattr(queue_mod, "DBOS", _FakeDBOS(fake_enqueue))
    monkeypatch.setattr(webhook_mod, "dedup_once", first_time)

    resp = _post({}, path="/webhook/caddy")

    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 1
    assert calls[0][1] == "alert_triage_workflow"
    assert calls[0][2]["signal"]["source"] == "caddy"


def test_enqueues_one_workflow_per_alert(ingress, monkeypatch):
    ingress(TOKEN)
    calls: list[tuple] = []

    async def fake_enqueue(queue, workflow, payload):
        calls.append((queue, workflow.__name__, payload))

    async def first_time(key, ttl):
        return True

    # 入队的规矩在 workflows/queue.py:DBOS 在那一边,不在路由里
    monkeypatch.setattr(queue_mod, "DBOS", _FakeDBOS(fake_enqueue))
    monkeypatch.setattr(webhook_mod, "dedup_once", first_time)

    resp = _post(
        {"alerts": [_alert(), _alert(fingerprint="def456")]}, {"X-Gwei-Token": TOKEN}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["count"] == 2
    assert [call[1] for call in calls] == ["alert_triage_workflow", "alert_triage_workflow"]
    assert calls[0][2]["signal"]["source"] == "alertmanager"
    assert calls[0][2]["tenant_slug"] == config.settings.default_tenant_slug


def test_a_repeated_delivery_is_deduped(ingress, monkeypatch):
    ingress(TOKEN)

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