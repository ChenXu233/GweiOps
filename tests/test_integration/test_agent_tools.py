# tests/test_integration/test_agent_tools.py
"""出口:沙箱里的 agent 只能从这里改变外部世界,每次改都落一行账。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from engine.agent import ToolCall, run_tool, tool_specs
from engine.change_unit import JsonlLedger, Window
from engine.plugin_manager.manifest import EffectDecl

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
        return {"handle": "h-1", "echo": dict(args)}

    async def undo(self, task, args, handle):
        return {}

    async def verify(self, effect, handle):
        return True, {"running_replicas": 3}


class Registry:
    def __init__(self, *, provider=None, menu=None, read=None) -> None:
        self.provider = provider
        self.menu = MENU if menu is None else menu
        self.read = read if read is not None else {"ok": True}
        self.read_calls: list[tuple[str, dict]] = []

    def declared_effects(self):
        return self.menu

    def effect_decl(self, capability, tenant="", binding=""):
        if self.provider is None:
            raise LookupError(f"nobody declares {capability}")
        return self.provider, DECL

    async def run_capability(self, capability, params):
        self.read_calls.append((capability, params))
        return dict(self.read)

    def names(self):
        return ["fake"]

    def manifest(self, name):
        return SimpleNamespace(capabilities=["issue.read", "compose.scale"])


def _ledger(tmp_path) -> JsonlLedger:
    return JsonlLedger(tmp_path / "ledger.jsonl")


def _rows(ledger: JsonlLedger) -> list[dict]:
    return asyncio.run(ledger.latest())


# ---------------------------------------------------------------------------
# 改世界的出口:走完整条闸门,落一行账
# ---------------------------------------------------------------------------


def test_a_mutating_exit_becomes_a_change_unit(tmp_path):
    ledger = _ledger(tmp_path)
    provider = Provider()
    result = asyncio.run(
        run_tool(
            ToolCall("compose.scale", {"service": "web", "replicas": 3}),
            registry=Registry(provider=provider),
            ledger=ledger,
            binding=BINDING,
            idem_base="wf-1",
            index=0,
            summary="错误率上升,加副本",
        )
    )

    assert result.ok is True
    assert result.verdict == "kept"
    assert provider.executed == 1

    rows = _rows(ledger)
    assert len(rows) == 1
    assert rows[0]["effect"]["capability"] == "compose.scale"
    assert rows[0]["effect"]["args"]["replicas"] == 3
    assert rows[0]["intent"]["summary"] == "错误率上升,加副本"


def test_a_blocked_exit_tells_the_agent_why(tmp_path):
    ledger = _ledger(tmp_path)
    provider = Provider(pre=Window())  # 读不到窗口
    result = asyncio.run(
        run_tool(
            ToolCall("compose.scale", {"service": "web"}),
            registry=Registry(provider=provider),
            ledger=ledger,
            binding=BINDING,
            idem_base="wf-1",
        )
    )

    assert result.ok is False
    assert result.verdict == "blocked"
    assert "读不到" in result.reason
    assert provider.executed == 0


def test_missing_provider_is_a_result_not_an_exception(tmp_path):
    result = asyncio.run(
        run_tool(
            ToolCall("compose.scale", {"service": "web"}),
            registry=Registry(provider=None),
            ledger=_ledger(tmp_path),
            binding=BINDING,
        )
    )
    assert result.ok is False
    assert "没有能执行" in result.reason


# ---------------------------------------------------------------------------
# 只读口:不落账
# ---------------------------------------------------------------------------


def test_a_read_exit_leaves_the_ledger_alone(tmp_path):
    ledger = _ledger(tmp_path)
    registry = Registry(provider=Provider())
    result = asyncio.run(
        run_tool(
            ToolCall("issue.read", {"repo": "o/r", "number": 1}),
            registry=registry,
            ledger=ledger,
            binding=BINDING,
        )
    )

    assert result.ok is True
    assert registry.read_calls == [("issue.read", {"repo": "o/r", "number": 1})]
    assert _rows(ledger) == []


def test_an_unknown_read_exit_is_also_a_result(tmp_path):
    class Boom(Registry):
        async def run_capability(self, capability, params):
            raise LookupError("no such thing")

    result = asyncio.run(
        run_tool(
            ToolCall("nothing.read", {}),
            registry=Boom(provider=Provider()),
            ledger=_ledger(tmp_path),
        )
    )
    assert result.ok is False
    assert "没有这个出口" in result.reason


# ---------------------------------------------------------------------------
# 出口清单:只列声明过的东西
# ---------------------------------------------------------------------------


def test_exit_specs_come_from_declarations_and_read_suffix():
    specs = tool_specs(Registry(provider=Provider()))
    names = [spec["function"]["name"] for spec in specs]
    assert names == ["compose.scale", "issue.read"]

    mutating = specs[0]["function"]["parameters"]
    assert set(mutating["properties"]) == {"project_dir", "service", "replicas"}
    assert mutating["additionalProperties"] is False


def test_an_undeclared_capability_is_not_an_exit():
    specs = tool_specs(Registry(provider=Provider(), menu={}))
    names = [spec["function"]["name"] for spec in specs]
    assert "compose.scale" not in names
