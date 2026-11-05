# tests/test_integration/test_api_auth.py
"""控制台令牌:谁在调用、代表哪个租户,从备注变成事实。"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.api.auth import TokenConfigError, load_tokens
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

OPERATOR = "t-operate:acme:值班人:operate"
VIEWER = "t-read:acme:只读:read"
ROOT = "t-root:*:维护者:operate"


class Provider:
    binding = "github"
    tenant = ""

    def __init__(self) -> None:
        self.undone: list[str] = []

    async def window(self, effect, handle):
        return Window(unbounded=True, source="fake")

    async def execute(self, task, args):
        return {"handle": "99"}

    async def undo(self, task, args, handle):
        self.undone.append(handle)
        return {}

    async def verify(self, effect, handle):
        return True, {"comment_exists": True}


def _unit(verdict="kept", handle="42", unit_id="u1", tenant="acme"):
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
        tenant=tenant,
        binding="github",
        handle=handle,
        window=Window(unbounded=True, source="test"),
        verdict=verdict,
        reason="验证通过",
    )


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "change_ledger_backend", "file")
    monkeypatch.setattr(config.settings, "change_ledger_path", str(tmp_path / "ledger.jsonl"))
    return JsonlLedger(config.settings.change_ledger_path)


def _client(raw_tokens: str) -> TestClient:
    app = FastAPI()
    app.include_router(changes_mod.router)

    @app.get("/api/health")
    def health() -> dict:  # 存活探测不该要令牌
        return {"status": "ok"}

    app.middleware("http")(changes_mod_middleware(raw_tokens))
    return TestClient(app)


def changes_mod_middleware(raw: str):
    from engine.api.auth import make_middleware

    return make_middleware(load_tokens(raw))


def _h(token: str) -> dict:
    return {"X-Gwei-Token": token}


# ---------------------------------------------------------------------------
# 没配令牌:不鉴权,但每个响应都说得出来
# ---------------------------------------------------------------------------


def test_without_tokens_everything_passes_and_says_so(ledger):
    asyncio.run(ledger.append(_unit()))
    resp = _client("").get("/api/changes")
    assert resp.status_code == 200
    assert resp.headers["X-Gwei-Auth"] == "off"


def test_with_tokens_the_header_flips_to_on(ledger):
    asyncio.run(ledger.append(_unit()))
    resp = _client(OPERATOR).get("/api/changes", headers=_h("t-operate"))
    assert resp.status_code == 200
    assert resp.headers["X-Gwei-Auth"] == "on"


# ---------------------------------------------------------------------------
# 没带令牌 / 带错令牌
# ---------------------------------------------------------------------------


def test_missing_token_is_401(ledger):
    assert _client(OPERATOR).get("/api/changes").status_code == 401


def test_wrong_token_is_401(ledger):
    assert _client(OPERATOR).get("/api/changes", headers=_h("nope")).status_code == 401


def test_health_needs_no_token(ledger):
    assert _client(OPERATOR).get("/api/health").status_code == 200


# ---------------------------------------------------------------------------
# 只读令牌不能改变世界
# ---------------------------------------------------------------------------


def test_read_token_cannot_approve(ledger):
    asyncio.run(ledger.append(_unit("blocked", handle=None)))
    resp = _client(VIEWER).post("/api/changes/u1/approve", headers=_h("t-read"))
    assert resp.status_code == 403


def test_operate_token_flows_into_the_ledger_not_the_query_string(ledger, monkeypatch):
    asyncio.run(ledger.append(_unit("blocked", handle=None)))
    provider = Provider()
    monkeypatch.setattr(
        changes_mod.registry, "effect_decl", lambda *a, **k: (provider, DECL)
    )

    resp = _client(OPERATOR).post(
        "/api/changes/u1/approve?by=冒充别人", headers=_h("t-operate")
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["latest"]["facts"]["authorized_by"] == "值班人"
    assert body["latest"]["facts"]["approval_reason"]


def test_rollback_records_who_pressed_it(ledger, monkeypatch):
    asyncio.run(ledger.append(_unit()))
    monkeypatch.setattr(
        changes_mod.registry, "effect_decl", lambda *a, **k: (Provider(), DECL)
    )
    resp = _client(OPERATOR).post(
        "/api/changes/u1/rollback", headers=_h("t-operate")
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["latest"]["facts"]["rolled_back_by"] == "值班人"


# ---------------------------------------------------------------------------
# 租户:令牌说什么就是什么
# ---------------------------------------------------------------------------


def test_a_tenant_token_only_sees_its_own_rows(ledger):
    asyncio.run(ledger.append(_unit(unit_id="a", tenant="acme")))
    asyncio.run(ledger.append(_unit(unit_id="b", tenant="other")))
    body = _client(OPERATOR).get("/api/changes", headers=_h("t-operate")).json()
    assert [row["id"] for row in body["items"]] == ["a"]


def test_asking_for_another_tenant_is_403(ledger):
    resp = _client(OPERATOR).get(
        "/api/changes?tenant=other", headers=_h("t-operate")
    )
    assert resp.status_code == 403


def test_a_wildcard_token_sees_everything(ledger):
    asyncio.run(ledger.append(_unit(unit_id="a", tenant="acme")))
    asyncio.run(ledger.append(_unit(unit_id="b", tenant="other")))
    body = _client(ROOT).get("/api/changes", headers=_h("t-root")).json()
    assert body["total"] == 2


def test_another_tenants_change_is_404_not_403(ledger):
    """看得见与否不该靠状态码泄露:不属于你的单元,就是不存在。"""
    asyncio.run(ledger.append(_unit(unit_id="b", tenant="other")))
    resp = _client(OPERATOR).get("/api/changes/b", headers=_h("t-operate"))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 配置:写错就拒绝启动,不静默降级
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["only-three:parts", "t:acme:值班人:admin", ":acme:值班人:operate", "dup:acme:a:read,dup:x:b:read"],
)
def test_a_malformed_token_line_refuses_to_start(raw):
    with pytest.raises(TokenConfigError):
        load_tokens(raw)


def test_tokens_parse_into_actors():
    tokens = load_tokens(f"{OPERATOR},{VIEWER}")
    assert tokens["t-operate"].tenant == "acme"
    assert tokens["t-operate"].scope == "operate"
    assert tokens["t-read"].scope == "read"
    assert load_tokens(ROOT)["t-root"].tenant == ""


def test_actor_repr_does_not_leak_the_token():
    actor = load_tokens(OPERATOR)["t-operate"]
    assert "t-operate" not in repr(actor)
