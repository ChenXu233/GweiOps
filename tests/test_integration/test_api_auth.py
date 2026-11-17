# tests/test_integration/test_api_auth.py
"""控制台令牌:谁在调用、代表哪个租户,从备注变成事实。"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI, Request
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


def _unit(verdict="kept", handle="42", unit_id="u1", tenant="acme", repo=""):
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
        repo=repo,
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


def test_asking_for_another_tenant_is_rejected(ledger):
    """工作区只能写在路径里。查询串再写一次不再生效 —— 这个迷你 app 只装了
    changes 那条路由,所以这里的判据是"它不再能改变分账",而不是状态码。"""
    asyncio.run(ledger.append(_unit()))
    resp = _client(OPERATOR).get(
        "/api/changes?tenant=other", headers=_h("t-operate")
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_the_workspace_segment_is_what_selects_the_account():
    """工作区写在路径里:折成路由认得的那条,再把里面那一段定成这次请求的工作区。

    折路径与定工作区是**同一步**:只折不定,请求会落到默认工作区;只定不折,路由
    认不出。所以这里一次验两件事 —— 折过去的路径命中了 `/api/probe`,而且
    `workspace_access()` 用的是路径里那一段。
    """
    from engine.api.auth import workspace_access

    app = FastAPI()

    @app.get("/api/probe")
    async def probe(request: Request) -> dict:  # 只在这一份 app 上存在
        return {"ws": workspace_access(request)}

    app.middleware("http")(changes_mod_middleware(OPERATOR))
    client = TestClient(app)

    own = client.get("/api/workspaces/acme/probe", headers=_h("t-operate"))
    assert own.status_code == 200
    assert own.json()["ws"] == "acme"

    other = client.get("/api/workspaces/other/probe", headers=_h("t-operate"))
    assert other.status_code == 403
    assert "other" in other.json()["detail"]


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


# ---------------------------------------------------------------------------
# 按仓库分工:只授了一个仓库的人,动不了别的仓库
# ---------------------------------------------------------------------------


SCOPED = "t-scoped:acme:只管一个仓库:operate"


def _client_with_actor(actor) -> TestClient:
    """一条把身份写死的通道:静态令牌没有细粒度权限,这里要的正是那种身份。"""
    from engine.api.auth import make_middleware

    app = FastAPI()
    app.include_router(changes_mod.router)

    async def middleware(request, call_next):
        request.state.actor = actor
        request.state.identity = None
        return await call_next(request)

    app.middleware("http")(middleware)
    return TestClient(app)


def _scoped_actor():
    from engine.api.auth import Actor

    return Actor(
        token_id="key",
        name="只管一个仓库",
        tenant="acme",
        scope="operate",
        permissions=frozenset({"changes.read"}),
        scoped_permissions={"changes.approve": frozenset({"github-acme-api"})},
    )


def test_a_repo_scoped_identity_can_approve_on_that_repo(ledger, monkeypatch):
    from engine.api.auth import set_auth_required

    asyncio.run(ledger.append(_unit("blocked", handle=None, repo="github-acme-api")))
    provider = Provider()
    monkeypatch.setattr(
        changes_mod.registry, "effect_decl", lambda *a, **k: (provider, DECL)
    )
    set_auth_required(True)
    try:
        resp = _client_with_actor(_scoped_actor()).post("/api/changes/u1/approve")
    finally:
        set_auth_required(False)
    assert resp.status_code == 200, resp.text


def test_a_repo_scoped_identity_cannot_approve_on_another_repo(ledger, monkeypatch):
    from engine.api.auth import set_auth_required

    asyncio.run(ledger.append(_unit("blocked", handle=None, repo="github-acme-web")))
    provider = Provider()
    monkeypatch.setattr(
        changes_mod.registry, "effect_decl", lambda *a, **k: (provider, DECL)
    )
    set_auth_required(True)
    try:
        resp = _client_with_actor(_scoped_actor()).post("/api/changes/u1/approve")
    finally:
        set_auth_required(False)
    assert resp.status_code == 403
    assert "changes.approve" in resp.json()["detail"]


def test_a_scoped_only_identity_cannot_act_workspace_wide():
    """只授了某几个仓库的权限,不等于在这个工作区上有这个权限,而且要说清楚。"""
    from fastapi import HTTPException

    from engine.api.auth import Actor, require, set_auth_required

    actor = Actor(
        token_id="key",
        name="只管一个仓库",
        tenant="acme",
        scope="operate",
        permissions=frozenset({"changes.read"}),
        scoped_permissions={"changes.approve": frozenset({"github-acme-api"})},
    )

    class Request:
        class state:  # noqa: N801 - 形似 request.state
            actor = None

    request = Request()
    request.state.actor = actor
    set_auth_required(True)
    try:
        # 不点名仓库 = 整个工作区,不该放行
        with pytest.raises(HTTPException) as raised:
            require(request, "changes.approve")
        assert raised.value.status_code == 403
        assert "只对具体范围生效" in raised.value.detail
        # 点名那个仓库就放行
        require(request, "changes.approve", "github-acme-api")
    finally:
        set_auth_required(False)


def test_a_project_scoped_identity_covers_the_whole_project():
    """授在项目上的人,对项目下每一个仓库都放行 —— 判定链 repo → project → 工作区。

    这一档必须问出来,不能在建身份时展开:项目下新加一个仓库时,没有人回来改
    这份身份,展开的那一份会漏掉它(engine/api/auth.py 的 require)。
    """
    from fastapi import HTTPException

    from engine.api.auth import Actor, require, set_auth_required

    actor = Actor(
        token_id="key",
        name="只管 acme",
        tenant="acme",
        scope="operate",
        permissions=frozenset({"changes.read"}),
        scoped_permissions={"changes.approve": frozenset({"acme"})},
    )

    class Request:
        class state:  # noqa: N801 - 形似 request.state
            actor = None

    request = Request()
    request.state.actor = actor
    set_auth_required(True)
    try:
        # 项目下的仓库,带上项目就放行
        require(request, "changes.approve", "github-acme-api", "acme")
        # 不带项目,只写仓库 slug:那一档没点这个仓库,不放行
        with pytest.raises(HTTPException) as raised:
            require(request, "changes.approve", "github-acme-api")
        assert raised.value.status_code == 403
        # 项目外的仓库不放行,即使它也叫 api
        with pytest.raises(HTTPException):
            require(request, "changes.approve", "github-other-api", "other")
    finally:
        set_auth_required(False)
