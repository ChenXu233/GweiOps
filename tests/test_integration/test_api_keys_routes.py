# tests/test_integration/test_api_keys_routes.py
"""密钥管理接口:谁都能看自己的钥匙串,只有够权限的人能签。

两条红线在接口上:签出去的权限不能超过自己的;明文只在那一次响应里。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.auth import ALL_PERMISSIONS
from engine.auth import keys as key_store
from engine.shared.config import config


@pytest.fixture
def env(tmp_path, monkeypatch):
    from engine.api.auth import load_tokens, make_middleware, set_auth_required
    from engine.api.routes import api_keys as keys_mod

    monkeypatch.setattr(config.settings, "change_ledger_backend", "file")
    monkeypatch.setattr(config.settings, "change_ledger_path", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setattr(config.settings, "default_tenant_slug", "acme")
    # 审计表在这套用例里不存在,写失败只喊一声,不影响接口
    from engine.auth import audit

    async def _skip(*args, **kwargs):
        return None

    monkeypatch.setattr(keys_mod.audit, "record", _skip)
    assert audit  # 引用着,免得被当成未使用的导入

    app = FastAPI()
    app.include_router(keys_mod.router)
    tokens = load_tokens("t-operate:acme:值班人:operate,t-read:acme:只读:read")
    app.middleware("http")(make_middleware(tokens))

    # 鉴权开关是模块级状态:用例会翻转它,测完必须翻回去,否则会漏到别的文件
    from engine.api import auth as auth_mod

    original = auth_mod.auth_required()
    yield SimpleNamespace(
        client=TestClient(app),
        monkeypatch=monkeypatch,
        tokens=tokens,
        set_auth_required=set_auth_required,
    )
    set_auth_required(original)


def _h(token: str = "t-operate") -> dict:
    return {"X-Gwei-Token": token}


def test_a_read_only_token_cannot_issue_a_key(env):
    resp = env.client.post(
        "/api/keys", json={"name": "x", "permissions": []}, headers=_h("t-read")
    )
    assert resp.status_code == 403


def test_the_plaintext_comes_back_exactly_once(env):
    issued = env.client.post(
        "/api/keys",
        json={"name": "claude-code", "permissions": ["changes.read"]},
        headers=_h(),
    ).json()

    assert issued["key"].startswith(key_store.KEY_PREFIX)
    listed = env.client.get("/api/keys", headers=_h()).json()
    assert [item["name"] for item in listed["items"]] == ["claude-code"]
    assert "key" not in listed["items"][0]


def test_the_issued_key_actually_works(env):
    issued = env.client.post(
        "/api/keys", json={"name": "a", "permissions": ["changes.read"]}, headers=_h()
    ).json()

    found = asyncio.run(key_store.resolve_key(issued["key"]))

    assert found is not None
    assert found.permissions == {"changes.read"}


def test_an_unknown_permission_is_refused(env):
    resp = env.client.post(
        "/api/keys", json={"name": "x", "permissions": ["made.up"]}, headers=_h()
    )
    assert resp.status_code == 422


def test_revoking_removes_it_from_the_working_set(env):
    issued = env.client.post(
        "/api/keys", json={"name": "leaked", "permissions": ["changes.read"]}, headers=_h()
    ).json()

    assert env.client.delete(f"/api/keys/{issued['id']}", headers=_h()).status_code == 200
    assert asyncio.run(key_store.resolve_key(issued["key"])) is None
    # 记录还在:谁签的、什么时候用过还看得见
    assert [item["id"] for item in env.client.get("/api/keys", headers=_h()).json()["items"]] == [
        issued["id"]
    ]


def test_revoking_something_that_is_not_there_is_404(env):
    assert env.client.delete("/api/keys/nope", headers=_h()).status_code == 404


def test_a_session_may_only_issue_what_it_holds(env):
    """会话身份按自己手上的权限签,签不出超出自己的那一份。"""
    from engine.api.auth import Actor

    seen: list[Actor] = []

    async def middleware(request, call_next):
        request.state.actor = Actor(
            token_id="session",
            name="运维",
            tenant="acme",
            scope="operate",
            permissions=frozenset({"keys.manage", "changes.read"}),
            user_id="u-1",
        )
        return await call_next(request)

    app = FastAPI()
    from engine.api.routes import api_keys as keys_mod

    app.include_router(keys_mod.router)
    app.middleware("http")(middleware)
    client = TestClient(app)
    seen.append(Actor("x", "y"))

    ok = client.post(
        "/api/keys", json={"name": "in-scope", "permissions": ["changes.read"]}
    )
    over = client.post(
        "/api/keys", json={"name": "over", "permissions": ["settings.write"]}
    )

    assert ok.status_code == 200
    assert over.status_code == 403
    assert "settings.write" in over.json()["detail"]


def test_a_key_shaped_string_that_resolves_to_nothing_is_401(env):
    """认不出的 gwei_ 前缀不落到"没配凭据就不鉴权"那一侧。

    没配任何凭据的部署里,这把东西如果被当成匿名请求,吊销就没有意义了:
    它只是从"这把密钥"降级成"自报租户的路人"。
    """
    env.set_auth_required(False)
    env.tokens.clear()

    resp = env.client.get(
        "/api/keys", headers={"X-Gwei-Token": key_store.KEY_PREFIX + "made-up"}
    )

    assert resp.status_code == 401
    assert "吊销" in resp.json()["detail"]


def test_every_permission_in_the_catalogue_can_be_issued(env):
    issued = env.client.post(
        "/api/keys", json={"name": "all", "permissions": sorted(ALL_PERMISSIONS)}, headers=_h()
    )
    assert issued.status_code == 200
    assert set(issued.json()["permissions"]) == set(ALL_PERMISSIONS)
