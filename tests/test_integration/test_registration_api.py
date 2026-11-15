# tests/test_integration/test_registration_api.py
"""注册这条路对外的几个端点:发码、核验、找回、OIDC 入口。

不连库:注册对库的那一半(码的比对、申请、建号)要真实 Postgres,
在 test_registration_flow.py 里跑。这里测的是**接口层的口径** ——
开关关着怎么答、通道没配怎么答、有没有泄露不该说的东西。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.api.routes import registration as reg_routes
from engine.auth import registration as policy_mod
from engine.shared.config import config


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(reg_routes.router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _registration_off(monkeypatch):
    monkeypatch.setattr(config.settings, "registration_enabled", False)
    monkeypatch.setattr(config.settings, "registration_methods", "email")
    monkeypatch.setattr(config.settings, "registration_test_code", "")
    config.apply_stored({})
    policy_mod.rate_forget("new@example.com")
    yield
    config.apply_stored({})


def test_policy_says_off_by_default(client):
    body = client.get("/api/auth/registration/policy").json()
    assert body == {
        "enabled": False,
        "methods": ["email"],
        "requires_verification": True,
        "code_ttl_minutes": 15,
        "oidc": {"available": False, "label": "用统一身份登录"},
    }


def test_start_is_refused_when_registration_is_off(client):
    resp = client.post(
        "/api/auth/register/start", json={"method": "email", "contact": "new@example.com"}
    )
    assert resp.status_code == 403
    assert "注册方式" in resp.json()["detail"]


def test_start_refuses_an_unknown_method(client, monkeypatch):
    monkeypatch.setattr(config.settings, "registration_enabled", True)
    resp = client.post(
        "/api/auth/register/start", json={"method": "sms", "contact": "13800000000"}
    )
    assert resp.status_code == 400


def test_a_missing_channel_says_what_to_configure(client, monkeypatch):
    # 没配通道时不能"假装发了":那等于核验被静默跳过
    monkeypatch.setattr(config.settings, "registration_enabled", True)
    monkeypatch.setattr(config.settings, "email_provider", "smtp")
    monkeypatch.setattr(config.settings, "smtp_host", "")
    monkeypatch.setattr(reg_routes.reg, "contact_taken", _async_false())

    resp = client.post(
        "/api/auth/register/start", json={"method": "email", "contact": "new@example.com"}
    )
    assert resp.status_code == 503
    assert "SMTP_HOST" in resp.json()["detail"]


def test_console_channel_delivers_and_never_echoes_the_code(client, monkeypatch, caplog):
    monkeypatch.setattr(config.settings, "registration_enabled", True)
    monkeypatch.setattr(config.settings, "email_provider", "console")
    monkeypatch.setattr(reg_routes.reg, "contact_taken", _async_false())
    monkeypatch.setattr(reg_routes.reg, "issue_code", _async_code("654321"))

    resp = client.post(
        "/api/auth/register/start", json={"method": "email", "contact": "New@Example.com"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    # 默认不回显验证码 —— 回显等于没有核验
    assert "test_code" not in body
    assert "654321" in caplog.text


def test_a_configured_test_code_is_echoed(client, monkeypatch):
    # 自部署联调时配了固定码才回显:那是有意为之,不是漏
    monkeypatch.setattr(config.settings, "registration_enabled", True)
    monkeypatch.setattr(config.settings, "registration_test_code", "111111")
    monkeypatch.setattr(config.settings, "email_provider", "console")
    monkeypatch.setattr(reg_routes.reg, "contact_taken", _async_false())
    monkeypatch.setattr(reg_routes.reg, "issue_code", _async_code("111111"))

    body = client.post(
        "/api/auth/register/start", json={"method": "email", "contact": "new@example.com"}
    ).json()
    assert body["test_code"] == "111111"


def test_rate_limit_answers_429(client, monkeypatch):
    monkeypatch.setattr(config.settings, "registration_enabled", True)
    monkeypatch.setattr(config.settings, "registration_rate_limit", 1)
    monkeypatch.setattr(config.settings, "email_provider", "console")
    monkeypatch.setattr(reg_routes.reg, "contact_taken", _async_false())
    monkeypatch.setattr(reg_routes.reg, "issue_code", _async_code("654321"))

    payload = {"method": "email", "contact": "new@example.com"}
    assert client.post("/api/auth/register/start", json=payload).status_code == 200
    assert client.post("/api/auth/register/start", json=payload).status_code == 429


def test_an_already_registered_contact_says_so(client, monkeypatch):
    # 注册不是登录:含糊其辞只会让人反复试
    monkeypatch.setattr(config.settings, "registration_enabled", True)
    monkeypatch.setattr(reg_routes.reg, "contact_taken", _async_true())
    resp = client.post(
        "/api/auth/register/start", json={"method": "email", "contact": "new@example.com"}
    )
    assert resp.status_code == 409


def test_reset_does_not_leak_whether_the_account_exists(client, monkeypatch):
    # 找回密码两边回同一句话:区分"有账号"与"没账号"是给攻击者的礼物
    monkeypatch.setattr(config.settings, "registration_enabled", True)

    async def _no_account(email, policy):
        return None

    monkeypatch.setattr(reg_routes.reg, "issue_reset_token", _no_account)
    body = client.post("/api/auth/password/reset", json={"email": "nobody@example.com"})
    assert body.status_code == 200
    assert body.json()["ok"] is True
    assert "如果这个邮箱有账号" in body.json()["note"]


def test_oidc_authorize_is_refused_when_not_enabled(client):
    resp = client.get("/api/auth/oidc/authorize", follow_redirects=False)
    assert resp.status_code == 403


def _async_true():
    async def inner(*args, **kwargs):
        return True

    return inner


def _async_false():
    async def inner(*args, **kwargs):
        return False

    return inner


def _async_code(code: str):
    async def inner(*args, **kwargs):
        return code

    return inner
