# tests/test_integration/test_console_agent.py
"""控制台助手:改世界的调用多一道人工批准,其余与出口同一条闸门。

覆盖:权限收窄与上限、按调用者当前权限重算(防静默提权)、批准/拒绝、
只读免批、会话与对话落库、bub 循环驱动工具。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from engine.agent import console as store
from engine.change_unit import JsonlLedger, Window
from engine.plugin_manager.manifest import EffectDecl
from engine.shared.config import config

def _load_console_plugin_loop():
    """插件的循环模块。

    插件目录名带连字符(`console-agent`),不是合法的 Python 包路径,所以按文件路径
    载入。测试要验的是"循环在插件里",不是"探一下核心里的旧副本"。
    """
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "plugins"
        / "builtin"
        / "agents"
        / "console-agent"
        / "loop.py"
    )
    spec = importlib.util.spec_from_file_location("console_agent_loop", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


loop_mod = _load_console_plugin_loop()

OPERATOR = "t-operate:acme:值班人:operate"
VIEWER = "t-read:acme:只读:read"
# 有权限集的密钥式身份:权限就是它的全部
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

    def best_capability_provider(self, capability):
        """循环由 `console.chat` 提供者给(见 `_ScriptedProvider`)。"""
        from engine.agent.provider import CAPABILITY

        if capability == CAPABILITY:
            return _ScriptedProvider()
        return None


class Role:
    """测试里的身份,与 `engine.api.auth.Actor` 同形状。"""

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
    import importlib

    from engine.api.auth import load_tokens, make_middleware
    from engine.api.routes import console_agent as routes

    monkeypatch.setattr(config.settings, "change_ledger_backend", "file")
    monkeypatch.setattr(config.settings, "change_ledger_path", str(tmp_path / "ledger.jsonl"))
    stub = Registry()
    monkeypatch.setattr(routes, "registry", stub)

    # 会话与对话落库用内存 SQLite,不碰部署里的 Postgres
    test_engine = create_async_engine("sqlite+aiosqlite://")
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    # `engine.db.engine` 被包 `__init__` 的同名对象遮住,只能从 sys.modules 拿
    db_engine = importlib.import_module("engine.db.engine")
    monkeypatch.setattr(db_engine, "async_session_factory", factory)
    monkeypatch.setattr(db_engine, "engine", test_engine)

    async def schema():
        from engine.agent.console import ensure_schema

        await ensure_schema()

    asyncio.run(schema())
    LOOP_SCRIPT.clear()
    SEEN.clear()
    # 循环是插件提供的:替身注册表的 `console.chat` 返回按剧本走的 agent
    # (见 `Registry.best_capability_provider`)
    monkeypatch.setattr(config.settings, "llm_api_key", "sk-test")
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
        factory=factory,
    )
    store.reset()
    store.reset_pending()
    asyncio.run(test_engine.dispose())


def _rows(env, session_id: str) -> list[dict]:
    return asyncio.run(store.history(session_id))


# 模型侧的剧本与记录:各用例自己填,env 装进去。
# bub 的循环由 `ScriptedAgent` 代替,测的是平台侧的接线,不是 bub 本身。
LOOP_SCRIPT: list[dict] = []
SEEN: list[dict] = []


class _ScriptedProvider:
    """声明 `console.chat` 的替身:循环由剧本驱动,测的是平台侧接线。"""

    binding = ""
    tenant = ""

    def build(self, *, session, registry, actor=None):
        return ScriptedAgent(session=session, registry=registry, actor=actor)


class ScriptedAgent:
    """按剧本走的假 bub agent;事件名与形状(text / tool_call / tool_result)同 bub。
    """

    def __init__(self, *, session, registry, actor=None) -> None:
        self.session = session
        self.registry = registry
        self.actor = actor

    def run(self, prompt, *, tape, **kw):
        return _ScriptedRun(self.session, self.registry, self.actor)


class _ScriptedRun:
    def __init__(self, session, registry, actor) -> None:
        self.session = session
        self.registry = registry
        self.actor = actor

    async def __aenter__(self):
        from engine.agent.console import bub_tools

        tools = bub_tools(self.session, self.registry, self.actor)
        SEEN.append({"tools": [t.name for t in tools]})
        self._pending: list[tuple[str, dict]] = []
        # 一轮可有多步:每步一个剧本,直到剧本用完或某步不再要工具
        while True:
            step = LOOP_SCRIPT.pop(0) if LOOP_SCRIPT else {"content": "好的", "tool_calls": []}
            if step.get("content"):
                self._pending.append(("text", {"delta": step["content"]}))
            for call in step.get("tool_calls") or ():
                self._pending.append(("tool_call", {"tool_calls": [call]}))
                handler = {t.name: t.handler for t in tools}[call["name"]]
                result = await handler(**(call.get("args") or {}))
                self._pending.append(("tool_result", {"tool_results": [result]}))
            if not step.get("tool_calls"):
                break
        return self

    async def __aexit__(self, *exc):
        return False

    async def __aiter__(self):
        for kind, data in self._pending:
            yield SimpleNamespace(kind=kind, data=data)


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
    # 静态令牌的 operate 即全部,与密钥路径同口径(见 engine/auth/keys.py)
    assert {"changes.read", "changes.execute", "settings.read"} <= set(body["permissions"])
    names = {t["name"] for t in body["available"]}
    assert names == {"changes.read", "compose.scale"}
    mutating = {t["name"]: t["mutating"] for t in body["available"]}
    assert mutating["compose.scale"] is True


def test_a_read_only_identity_does_not_get_the_effect(env):
    """只读令牌签不出写权限,会话可见工具只剩只读。"""
    resp = env.client.post("/api/console/session", json={}, headers=_h("t-read"))

    body = resp.json()
    assert resp.status_code == 200
    assert "changes.execute" not in body["permissions"]
    # 静态令牌没有权限集,tool_visible 只认 `.read` 后缀,与 MCP 侧同结果
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


def _session(*, storage: bool = False, **kw) -> store.ConsoleSession:
    """默认不落库(这批用例只判权限与闸门);查审计的用例传 `storage=True`。
    """
    actor = Role({"changes.read", "changes.execute"}, bindings={BINDING})
    return asyncio.run(
        store.open_session(actor=actor, tenant="acme", binding=BINDING, storage=storage, **kw)
    )


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
        # 等待待批调用出现
        for _ in range(100):
            call = store.pending_of(session)
            if call is not None:
                break
            await asyncio.sleep(0.02)
        assert call is not None
        assert call.name == "compose.scale"
        await store.decide(session, call.id, True)
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
        await store.decide(session, call.id, False, "现在别动")
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
        from engine.agent.provider import build_agent

        agent = build_agent(session=session, registry=env.stub)
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

    # 模型看到的名字是 compose_scale(点换下划线),落账的是 compose.scale
    assert tools == ["compose_scale"]
    assert "加好了" in "".join(texts)
    assert SEEN[0]["tools"] == ["compose_scale", "changes_read"]
    # 工具已执行:账本多一行,动作计数递增
    assert asyncio.run(env.ledger.latest())[0]["verdict"] == "kept"
    assert session.actions == 1


def test_the_loop_only_sees_what_the_session_allows(env):
    session = _session(permissions=["changes.read"])

    async def run():
        from engine.agent.provider import build_agent

        agent = build_agent(session=session, registry=env.stub)
        async with agent.run("看账本", tape="t2") as stream:
            async for _event in stream:
                pass

    asyncio.run(run())

    assert SEEN[0]["tools"] == ["changes_read"]


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

    # 出口清单里改世界的在前、只读的在后,顺序即 `tool_specs` 的顺序
    assert [t["name"] for t in body["tools"]] == ["compose.scale", "changes.read"]
    assert body["resources"] == [BINDING]
    assert json.dumps(body)  # 可序列化,前端直接吃


# ---------------------------------------------------------------------------
# 不静默提权:会话是上限,不是签名
# ---------------------------------------------------------------------------


def test_a_revoked_permission_is_gone_on_the_next_turn(env):
    """人的权限被收回后,下一轮不能按开会话时的权限算。"""
    session = _session()

    narrowed = Role({"changes.read"}, bindings={BINDING})
    out = asyncio.run(store.call_tool(session, env.stub, "compose.scale", {}, actor=narrowed))

    assert out["ok"] is False
    assert "changes.execute" in out["reason"]
    # 清单同步收窄:工具清单与判据是同一条
    names = [t["name"] for t in store.describe_tools(session, env.stub, narrowed)]
    assert names == ["changes.read"]


def test_the_session_is_only_an_upper_bound(env):
    """会话收窄后,调用者再宽也没用:取交集不取并集。"""
    session = _session(permissions=["changes.read"])
    wide = Role({"changes.read", "changes.execute"}, bindings={BINDING})

    assert "compose.scale" not in {t["name"] for t in store.describe_tools(session, env.stub, wide)}
    out = asyncio.run(store.call_tool(session, env.stub, "compose.scale", {}, actor=wide))
    assert out["ok"] is False


def test_approval_rechecks_the_permission(env):
    """等待批准期间权限没了,点允许也要拒,否则等于延长旧权限。"""
    session = _session()
    narrowed = Role({"changes.read"}, bindings={BINDING})

    async def scenario():
        task = asyncio.create_task(store.call_tool(session, env.stub, "compose.scale", {"replicas": 1}))
        for _ in range(100):
            call = store.pending_of(session)
            if call is not None:
                break
            await asyncio.sleep(0.02)
        assert call is not None
        with pytest.raises(store.SessionError):
            await store.decide(session, call.id, True, actor=narrowed)
        await store.decide(session, call.id, False, "权限已收回", actor=narrowed)
        return await task

    out = asyncio.run(scenario())

    assert out["ok"] is False
    assert env.stub.provider.executed == 0


def test_a_read_only_identity_does_not_lose_its_read_tools(env):
    """`read` 只给只读口,不映射成空集——空集在静态令牌路径上会放行更多。"""
    assert "changes.read" in store._scope_permissions("read")
    assert "changes.execute" not in store._scope_permissions("read")


# ---------------------------------------------------------------------------
# 落库:会话与每一句都要能回查
# ---------------------------------------------------------------------------


def test_the_session_is_persisted(env):
    opened = _open(env)

    rows = asyncio.run(store.history(opened["id"]))
    assert [r["role"] for r in rows] == ["session"]
    assert rows[0]["payload"]["action"] == "session.open"


def test_a_session_survives_the_process_cache(env):
    """缓存清空(相当于进程重启)后,会话连权限上限一起从库里读回。"""
    opened = _open(env, permissions=["changes.read"])
    store.reset()

    body = env.client.get(f"/api/console/session/{opened['id']}", headers=_h()).json()

    assert body["permissions"] == ["changes.read"]
    assert [t["name"] for t in body["available"]] == ["changes.read"]


def test_a_refusal_is_on_the_record(env):
    session = _session(storage=True)

    async def scenario():
        task = asyncio.create_task(store.call_tool(session, env.stub, "compose.scale", {"replicas": 2}))
        for _ in range(100):
            call = store.pending_of(session)
            if call is not None:
                break
            await asyncio.sleep(0.02)
        await store.decide(session, call.id, False, "现在别动")
        return await task

    asyncio.run(scenario())

    rows = _rows(env, session.id)
    assert [r["role"] for r in rows] == ["session", "tool_call", "denied"]
    assert rows[2]["payload"]["reason"] == "现在别动"
    # 拒绝不落账本:改世界的动作没做
    assert asyncio.run(env.ledger.latest()) == []


def test_a_permission_refusal_is_on_the_record(env):
    session = _session(permissions=["changes.read"], storage=True)

    asyncio.run(store.call_tool(session, env.stub, "compose.scale", {}))

    rows = _rows(env, session.id)
    assert [r["role"] for r in rows] == ["session", "tool_call", "tool_result"]
    assert rows[2]["payload"]["ok"] is False


def test_the_turn_is_recorded(env):
    LOOP_SCRIPT.append({"content": "看过了", "tool_calls": []})
    opened = _open(env)

    env.client.post(
        f"/api/console/session/{opened['id']}/turn",
        json={"message": "现在怎么样"},
        headers=_h(),
    )

    rows = _rows(env, opened["id"])
    assert [r["role"] for r in rows] == ["session", "user", "assistant"]
    assert rows[1]["content"] == "现在怎么样"
    assert rows[2]["content"] == "看过了"


def test_the_messages_endpoint_is_the_audit_trail(env):
    opened = _open(env)

    body = env.client.get(
        f"/api/console/session/{opened['id']}/messages", headers=_h()
    ).json()

    assert body["messages"][0]["payload"]["action"] == "session.open"


# ---------------------------------------------------------------------------
# 模型:交给 bub 自己的 provider,不再绕 litellm
# ---------------------------------------------------------------------------


def test_the_spec_is_provider_colon_model(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "gemini")
    monkeypatch.setattr(config.settings, "llm_model", "gemini-2.5-pro")

    # litellm 与 republic 的 provider 名不总一致,对不上的在此换掉
    assert loop_mod.model_spec() == "google:gemini-2.5-pro"


def test_a_model_string_with_a_prefix_wins(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "openai")
    monkeypatch.setattr(config.settings, "llm_model", "deepseek/deepseek-chat")

    assert loop_mod.model_spec() == "deepseek:deepseek-chat"


def test_client_options_carry_the_key_and_the_endpoint(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_api_key", "sk-test")
    monkeypatch.setattr(config.settings, "llm_base_url", "http://localhost:8000/v1")

    options = loop_mod.client_options("openai:qwen")

    assert options == {"api_key": "sk-test", "base_url": "http://localhost:8000/v1", "model": "qwen"}


def test_the_agent_uses_bubs_model_not_a_translation(monkeypatch):
    """会话 agent 的模型是 bub 的 `BubModel`(provider:model),不是自己摊事件流。

    此用例要真 bub,绕开 env 里的替身直接构造。
    """
    try:
        from bub.builtin.model import BubModel  # noqa: F401
    except ImportError:
        pytest.skip("没装 bub")
    real = _load_console_plugin_loop()

    monkeypatch.setattr(real, "HAS_BUB", True)

    session = _session()
    agent = real.build_agent(session=session, registry=Registry())

    assert type(agent.model).__name__ == "BubModel"
    assert ":" in agent.model.spec


# ---------------------------------------------------------------------------
# 模型不可用:报错要能被搜索到
# ---------------------------------------------------------------------------


def test_a_missing_key_is_an_error_not_a_persona(env, monkeypatch):
    """没有密钥时如实报错,而且这句话要能检索到。

    这条要真的走一遍插件的 `build_agent`:替身 agent 不检查密钥,拿它测的是
    "替身能不能跑",不是"没配密钥会怎样"。
    """
    monkeypatch.setattr(config.settings, "llm_api_key", "")
    real = _load_console_plugin_loop()

    class RealProvider:
        def build(self, **kwargs):
            if real.missing_key():
                raise LookupError(real.NOT_CONFIGURED)
            return real.build_agent(**kwargs)

    monkeypatch.setattr(
        env.stub,
        "best_capability_provider",
        lambda capability: RealProvider() if capability == "console.chat" else None,
    )
    opened = _open(env)

    resp = env.client.post(
        f"/api/console/session/{opened['id']}/turn",
        json={"message": "在吗"},
        headers=_h(),
    )

    assert "event: error" in resp.text
    assert "LLM_API_KEY" in resp.text
    # 报错文案不拟人
    assert "说不了话" not in resp.text
    rows = _rows(env, opened["id"])
    assert [r["role"] for r in rows][-1] == "error"
