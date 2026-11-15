# tests/test_integration/test_console_agent.py
"""控制台里的那个助手:多一道人的允许,其余全是同一条闸门。

要紧的几件事各有一条用例盯着:
- 权限:会话只能越用越窄,签的时候不能超过这个人手上的;
- 允许:改世界的调用先摆到人面前,点了允许才执行,点了拒绝就当没做;
- 只读:看一眼不需要批准;
- loop:bub 的循环真的会被驱动(模型要工具 → 工具跑 → 结果回给模型)。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.agent import console as store
from engine.agent import loop as loop_mod
from engine.change_unit import JsonlLedger, Window
from engine.plugin_manager.manifest import EffectDecl
from engine.shared.config import config

OPERATOR = "t-operate:acme:值班人:operate"
VIEWER = "t-read:acme:只读:read"
# 有权限集的密钥式身份:权限是它的全部,没有"默认全放"
OPERATOR_PERMISSIONS = frozenset({"changes.read", "changes.execute", "settings.read"})
BINDING = "github"

DECL = EffectDecl(
    capability="compose.scale",
    execute_task="scale",
    undo_task="undo_scale",
    undo_kind="symmetric",
    window_read="project_present",
    verify=({"query": "running_replicas", "expect": ">= 1"},),
    label="调整 compose 服务副本数",
    execute_args=("project_dir", "service", "replicas"),
)

MENU = {"compose.scale": {"label": DECL.label, "args": list(DECL.execute_args)}}


class Provider:
    binding = BINDING
    tenant = ""

    def __init__(self) -> None:
        self.executed = 0

    async def window(self, effect, handle):
        return Window(unbounded=True, source="fake")

    async def execute(self, task, args):
        self.executed += 1
        return {"handle": "h-1"}

    async def undo(self, task, args, handle):
        return {}

    async def verify(self, effect, handle):
        return True, {"running_replicas": 3}


class Registry:
    def __init__(self) -> None:
        self.provider = Provider()

    def declared_effects(self):
        return MENU

    def effect_decl(self, capability, tenant="", binding=""):
        return self.provider, DECL

    async def run_capability(self, capability, params):
        if capability != "changes.read":
            raise LookupError(f"no provider for {capability}")
        return {"items": [], "count": 0}

    def tool_bindings(self, capability):
        return (BINDING,)

    def names(self):
        return ["fake"]

    def manifest(self, name):
        return SimpleNamespace(capabilities=["changes.read", "compose.scale"])

    def resources(self):
        return [BINDING]


class Role:
    """测试里的身份:与 `engine.api.auth.Actor` 同一形状。"""

    def __init__(self, permissions, bindings=frozenset(), static=False, name="值班人"):
        self.name = name
        self.permissions = frozenset(permissions)
        self.bindings = frozenset(bindings)
        self.static = static
        self.tools = frozenset()
        self.tenant = "acme"

    @property
    def can_write(self):
        return "changes.execute" in self.permissions


@pytest.fixture
def env(tmp_path, monkeypatch):
    from engine.api.auth import load_tokens, make_middleware
    from engine.api.routes import console_agent as routes

    monkeypatch.setattr(config.settings, "change_ledger_backend", "file")
    monkeypatch.setattr(config.settings, "change_ledger_path", str(tmp_path / "ledger.jsonl"))
    stub = Registry()
    monkeypatch.setattr(routes, "registry", stub)
    # 让"一次补全"走脚本,不打真模型
    async def fake_chat(llm, messages, tools):
        script = LOOP_SCRIPT.pop(0) if LOOP_SCRIPT else {"content": "好的", "tool_calls": []}
        SEEN.append({"messages": messages, "tools": tools})
        return script

    LOOP_SCRIPT.clear()
    SEEN.clear()
    monkeypatch.setattr(loop_mod, "chat", fake_chat)
    monkeypatch.setattr("engine.plugin_manager.registry", stub, raising=False)
    store.reset()
    store.reset_pending()

    app = FastAPI()
    app.include_router(routes.router)
    app.middleware("http")(make_middleware(load_tokens(f"{OPERATOR},{VIEWER}")))

    yield SimpleNamespace(
        client=TestClient(app),
        stub=stub,
        ledger=JsonlLedger(config.settings.change_ledger_path),
        monkeypatch=monkeypatch,
    )
    store.reset()
    store.reset_pending()


# 一次补全的剧本与记录:每个用例自己填,env 装进去
LOOP_SCRIPT: list[dict] = []
SEEN: list[dict] = []


def _h(token: str = "t-operate") -> dict:
    return {"X-Gwei-Token": token}


def _open(env, **body) -> dict:
    resp = env.client.post("/api/console/session", json=body, headers=_h())
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# 会话与权限
# ---------------------------------------------------------------------------


def test_it_needs_a_token(env):
    assert env.client.post("/api/console/session", json={}).status_code == 401


def test_a_session_starts_with_what_the_identity_has(env):
    body = _open(env)

    assert body["actor"] == "值班人"
    assert body["tenant"] == "acme"
    # 静态令牌的 operate 就是"全部":与密钥那条路径同一个口径(见 engine/auth/keys.py)
    assert {"changes.read", "changes.execute", "settings.read"} <= set(body["permissions"])
    names = {t["name"] for t in body["available"]}
    assert names == {"changes.read", "compose.scale"}
    mutating = {t["name"]: t["mutating"] for t in body["available"]}
    assert mutating["compose.scale"] is True


def test_a_read_only_identity_does_not_get_the_effect(env):
    """只读令牌 sign 不出一条写权限:会话里看得见的工具也就只剩只读的。"""
    resp = env.client.post("/api/console/session", json={}, headers=_h("t-read"))

    body = resp.json()
    assert resp.status_code == 200
    assert "changes.execute" not in body["permissions"]
    # 静态令牌没有权限集,tool_visible 只认 `.read` 后缀 —— 与 MCP 那一侧同一个结果
    assert "compose.scale" not in {t["name"] for t in body["available"]}


def test_a_session_cannot_hand_out_more_than_the_person_has(env):
    resp = env.client.post(
        "/api/console/session",
        json={"permissions": ["changes.read", "not.a.permission"]},
        headers=_h(),
    )

    assert resp.status_code == 403
    assert "not.a.permission" in resp.json()["detail"]


def test_narrowing_a_session_needs_no_approval(env):
    opened = _open(env)
    resp = env.client.patch(
        f"/api/console/session/{opened['id']}",
        json={"permissions": ["changes.read"]},
        headers=_h(),
    )

    assert resp.status_code == 200
    assert resp.json()["permissions"] == ["changes.read"]
    assert [t["name"] for t in resp.json()["available"]] == ["changes.read"]


def test_someone_elses_session_is_not_yours(env):
    opened = _open(env)
    resp = env.client.get(f"/api/console/session/{opened['id']}", headers=_h("t-read"))

    assert resp.status_code == 403


def test_a_tool_whitelist_narrows_the_session(env):
    body = _open(env, tools=["changes.read"])

    assert [t["name"] for t in body["available"]] == ["changes.read"]


# ---------------------------------------------------------------------------
# 改世界:先问人
# ---------------------------------------------------------------------------


def _session(**kw) -> store.ConsoleSession:
    actor = Role({"changes.read", "changes.execute"}, bindings={BINDING})
    return store.open_session(actor=actor, tenant="acme", binding=BINDING, **kw)


def _call(session, name: str, args: dict, registry) -> dict:
    return asyncio.run(store.call_tool(session, registry, name, args))


def test_a_read_only_tool_runs_without_asking(env):
    session = _session()

    out = _call(session, "changes.read", {"limit": 1}, env.stub)

    assert out["ok"] is True
    assert session.actions == 0


def test_an_effect_waits_for_a_person(env):
    session = _session()

    async def scenario():
        task = asyncio.create_task(
            store.call_tool(session, env.stub, "compose.scale", {"service": "web", "replicas": 3})
        )
        # 等它摆到人面前
        for _ in range(100):
            call = store.pending_of(session)
            if call is not None:
                break
            await asyncio.sleep(0.02)
        assert call is not None
        assert call.name == "compose.scale"
        store.decide(session, call.id, True)
        return await task

    out = asyncio.run(scenario())

    assert out["ok"] is True
    assert out["verdict"] == "kept"
    assert session.actions == 1
    rows = asyncio.run(env.ledger.latest())
    assert len(rows) == 1 and rows[0]["verdict"] == "kept"


def test_a_refused_effect_is_not_executed(env):
    session = _session()

    async def scenario():
        task = asyncio.create_task(
            store.call_tool(session, env.stub, "compose.scale", {"service": "web", "replicas": 3})
        )
        for _ in range(100):
            call = store.pending_of(session)
            if call is not None:
                break
            await asyncio.sleep(0.02)
        store.decide(session, call.id, False, "现在别动")
        return await task

    out = asyncio.run(scenario())

    assert out["ok"] is False
    assert "现在别动" in out["reason"]
    assert asyncio.run(env.ledger.latest()) == []


def test_confirmation_off_runs_straight_through(env):
    session = _session(confirm=False)

    out = _call(session, "compose.scale", {"service": "web", "replicas": 3}, env.stub)

    assert out["verdict"] == "kept"
    assert session.actions == 1


def test_the_action_budget_is_per_conversation(env):
    session = _session(confirm=False)
    for _ in range(store.MAX_ACTIONS):
        _call(session, "compose.scale", {"service": "web", "replicas": 3}, env.stub)

    out = _call(session, "compose.scale", {"service": "web", "replicas": 3}, env.stub)

    assert out["ok"] is False
    assert "上限" in out["reason"]


def test_a_tool_outside_the_session_is_refused(env):
    session = _session(permissions=["changes.read"])

    out = _call(session, "compose.scale", {"service": "web", "replicas": 3}, env.stub)

    assert out["ok"] is False
    assert "changes.execute" in out["reason"]


# ---------------------------------------------------------------------------
# 循环:交给 bub
# ---------------------------------------------------------------------------


def test_the_bub_loop_drives_a_tool_then_answers(env):
    """一轮真的跑一遍:模型先要工具,工具跑了,结果回给模型,模型收尾。"""
    session = _session(confirm=False)
    LOOP_SCRIPT.extend(
        [
            {
                "content": "",
                "tool_calls": [
                    {"id": "c1", "name": "compose_scale", "args": {"service": "web", "replicas": 3}}
                ],
            },
            {"content": "加好了", "tool_calls": []},
        ]
    )

    async def run():
        agent = loop_mod.session_agent(session=session, registry=env.stub)
        texts: list[str] = []
        tools: list[str] = []
        async with agent.run("把 web 加到 3 个副本", tape="t1") as stream:
            async for event in stream:
                if event.kind == "text":
                    texts.append(event.data.get("delta", ""))
                elif event.kind == "tool_call":
                    tools.extend(c["name"] for c in event.data.get("tool_calls") or ())
        return texts, tools

    texts, tools = asyncio.run(run())

    # 模型看到的名字是 compose_scale(点换成了下划线),落账的是 compose.scale
    assert tools == ["compose_scale"]
    assert "加好了" in "".join(texts)
    assert [t["function"]["name"] for t in SEEN[0]["tools"]] == ["compose_scale", "changes_read"]
    # 第二轮模型看到的就是工具跑完的结果
    assert any(m.get("role") == "tool" for m in SEEN[1]["messages"])
    assert session.actions == 1


def test_the_loop_only_sees_what_the_session_allows(env):
    session = _session(permissions=["changes.read"])

    async def run():
        agent = loop_mod.session_agent(session=session, registry=env.stub)
        async with agent.run("看账本", tape="t2") as stream:
            async for _event in stream:
                pass

    asyncio.run(run())

    assert [t["function"]["name"] for t in SEEN[0]["tools"]] == ["changes_read"]


# ---------------------------------------------------------------------------
# 接口:一连串事件摊给前端
# ---------------------------------------------------------------------------


def test_the_turn_endpoint_streams_events(env):
    LOOP_SCRIPT.append({"content": "我只是看一下", "tool_calls": []})
    opened = _open(env)

    resp = env.client.post(
        f"/api/console/session/{opened['id']}/turn",
        json={"message": "现在怎么样"},
        headers=_h(),
    )

    assert resp.status_code == 200
    assert "event: delta" in resp.text
    assert "event: done" in resp.text
    assert "我只是看一下" in resp.text


def test_the_available_tool_list_is_the_exit_menu(env):
    body = env.client.get("/api/console/tools", headers=_h()).json()

    # 出口清单里改世界的在前,只读的在后 —— 这份顺序就是 `tool_specs` 的顺序
    assert [t["name"] for t in body["tools"]] == ["compose.scale", "changes.read"]
    assert body["resources"] == [BINDING]
    assert json.dumps(body)  # 可序列化,前端直接吃
