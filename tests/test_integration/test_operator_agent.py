# tests/test_integration/test_operator_agent.py
"""值班 agent:循环在插件里,每一步改世界都落在同一本账上。"""

from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

from engine.change_unit import JsonlLedger, Window
from engine.llm.client import ToolChatResult
from engine.plugin_manager.manifest import EffectDecl
from engine.workflows import pipeline

BINDING = "local"

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
SIGNAL = {"source": "alertmanager", "subject": "high-error", "title": "web 错误率超 10%"}


def _module():
    return importlib.import_module("plugins.builtin.agents.operator.plugin")


class Provider:
    binding = BINDING
    tenant = ""

    def __init__(self, *, pre: Window | None = None) -> None:
        self.pre = pre or Window(unbounded=True, source="fake")
        self.executed = 0

    async def window(self, effect, handle):
        return self.pre

    async def execute(self, task, args):
        self.executed += 1
        return {"handle": "h-1"}

    async def undo(self, task, args, handle):
        return {}

    async def verify(self, effect, handle):
        return True, {"running_replicas": 3}


class Registry:
    def __init__(self, *, provider=None, menu=None, read_capabilities=None) -> None:
        self.provider = provider
        self.menu = MENU if menu is None else menu
        self.read_capabilities = (
            ["issue.read", "compose.scale"] if read_capabilities is None else read_capabilities
        )
        self.reads: list[tuple[str, dict]] = []

    def declared_effects(self):
        return self.menu

    def effect_decl(self, capability, tenant="", binding=""):
        if self.provider is None:
            raise LookupError(f"nobody declares {capability}")
        return self.provider, DECL

    async def run_capability(self, capability, params):
        self.reads.append((capability, params))
        return {"states": [{"service": "web", "running": 1}]}

    def names(self):
        return ["fake"]

    def manifest(self, name):
        return SimpleNamespace(capabilities=self.read_capabilities)


class FakeLLM:
    """按剧本吐 tool_calls,并记下每一轮它看到的消息。"""

    def __init__(self, turns) -> None:
        self.turns = list(turns)
        self.seen: list[list[dict]] = []

    async def call_with_tools(self, messages, tools):
        self.seen.append([dict(m) for m in messages])
        if self.turns:
            return self.turns.pop(0)
        # 剧本用完了:模型这一轮既没说话也没调工具,循环自然收尾
        return ToolChatResult()


def _call(name: str, **args) -> dict:
    return {"id": f"c-{name}", "name": name, "args": args}


def _agent(tmp_path, turns, **kw):
    module = _module()
    llm = FakeLLM(turns)
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")
    agent = module.OperatorAgent(
        llm_service=llm,
        registry=kw.pop("registry", Registry(provider=Provider())),
        ledger=ledger,
        **kw,
    )
    return agent, llm, ledger


def _handle(agent) -> dict:
    return asyncio.run(agent.handle({"signal": SIGNAL, "binding": BINDING, "idem_base": "wf-1"}))


# ---------------------------------------------------------------------------


def test_agent_reads_then_acts_and_the_exit_lands_in_the_ledger(tmp_path):
    agent, llm, ledger = _agent(
        tmp_path,
        [
            ToolChatResult(content="先看一眼", tool_calls=[_call("issue.read", repo="o/r")]),
            ToolChatResult(
                content="加副本",
                tool_calls=[_call("compose.scale", service="web", replicas=3)],
            ),
        ],
    )
    report = _handle(agent)

    assert report["summary"] == "加副本"
    assert [step["tool"] for step in report["steps"]] == ["issue.read", "compose.scale"]
    assert report["counts"] == {"ok": 1, "kept": 1}
    assert report["exhausted"] is False

    rows = asyncio.run(ledger.latest())
    assert len(rows) == 1
    assert rows[0]["verdict"] == "kept"
    assert rows[0]["effect"]["args"]["replicas"] == 3


def test_a_refused_exit_is_fed_back_with_its_reason(tmp_path):
    agent, llm, ledger = _agent(
        tmp_path,
        [
            ToolChatResult(
                tool_calls=[_call("compose.scale", service="web", replicas=9)]
            )
        ],
        registry=Registry(provider=Provider(pre=Window())),
    )
    report = _handle(agent)

    assert report["steps"][0]["result"]["verdict"] == "blocked"
    # 第二轮它看到的就是那句拒绝理由
    second_round = llm.seen[1]
    tool_messages = [m for m in second_round if m.get("role") == "tool"]
    assert tool_messages and "读不到" in tool_messages[-1]["content"]
    assert asyncio.run(ledger.latest())[0]["verdict"] == "blocked"


def test_no_tool_calls_means_it_stops(tmp_path):
    agent, llm, _ = _agent(tmp_path, [ToolChatResult(content="不用动,只是抖动")])
    report = _handle(agent)

    assert report["steps"] == []
    assert report["summary"] == "不用动,只是抖动"
    assert len(llm.seen) == 1


def test_the_budget_bounds_the_exits(tmp_path):
    forever = [
        ToolChatResult(tool_calls=[_call("issue.read", repo="o/r")]) for _ in range(5)
    ]
    agent, _, _ = _agent(tmp_path, forever, max_exits=2)
    report = _handle(agent)

    assert report["exhausted"] is True
    assert len(report["steps"]) == 2


def test_without_any_declared_exit_it_says_so_and_stops(tmp_path):
    agent, llm, _ = _agent(
        tmp_path,
        [],
        registry=Registry(provider=Provider(), menu={}, read_capabilities=[]),
    )
    report = _handle(agent)

    assert report["steps"] == []
    assert "没有声明过任何出口" in report["summary"]
    assert llm.seen == []


# ---------------------------------------------------------------------------
# 工作流:有 agent 就整场交给它,没有就走原来的声明式路径
# ---------------------------------------------------------------------------


class StubRegistry:
    def __init__(self, provider) -> None:
        self.provider = provider
        self.seen: dict | None = None

    def best_capability_provider(self, capability):
        return self.provider

    async def run_capability(self, capability, params):
        self.seen = params
        return {"summary": "agent 处理完了", "steps": [], "counts": {}, "exhausted": False}


def test_workflow_hands_the_incident_to_the_agent(monkeypatch):
    stub = StubRegistry(object())
    monkeypatch.setattr(pipeline, "registry", stub)
    out = asyncio.run(pipeline._handle_incident_impl({"signal": dict(SIGNAL)}))

    assert out["summary"] == "agent 处理完了"
    assert stub.seen["signal"]["title"] == SIGNAL["title"]
    assert stub.seen["binding"]


def test_workflow_falls_back_when_no_agent_is_registered(monkeypatch):
    monkeypatch.setattr(pipeline, "registry", StubRegistry(None))
    assert asyncio.run(pipeline._handle_incident_impl({"signal": dict(SIGNAL)})) is None
