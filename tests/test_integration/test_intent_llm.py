# tests/test_integration/test_intent_llm.py
"""模型起草 intent —— 重点不是它写得多好,是它写不出来的时候不编。"""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

from engine.llm.client import LLMCallResult
from engine.workflows import pipeline

AGENTS_DIR = Path("plugins/builtin/agents")

MENU = {
    "compose.scale": {
        "label": "调整 compose 服务副本数",
        "args": ["project_dir", "service", "replicas"],
    },
    "comment.create": {
        "label": "在 Issue / PR 上发一条评论",
        "args": ["repo", "issue_number", "body"],
    },
}

SIGNAL = {
    "source": "alertmanager",
    "subject": "high-error-rate",
    "title": "web 错误率超过 10%",
    "detail": "5xx 占比 12%",
}


def _plugin_module():
    return importlib.import_module("plugins.builtin.agents.intent-llm.plugin")


class FakeLLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, str]] = []

    async def call(self, system_prompt: str, user_prompt: str) -> LLMCallResult:
        self.calls.append((system_prompt, user_prompt))
        return LLMCallResult(content=self.content, tokens_used=0, model="fake")


def _planner(content: str, menu: dict | None = None):
    module = _plugin_module()
    return module.LLMIntentPlanner(
        llm_service=FakeLLM(content),
        menu_provider=lambda: MENU if menu is None else menu,
    )


def _propose(planner, params: dict | None = None):
    return asyncio.run(planner.propose(params or {"signal": SIGNAL}))


def _answer(**overrides) -> str:
    payload = {
        "summary": "把 web 扩到 4 副本以分摊流量",
        "evidence": [{"kind": "alertmanager", "ref": "high-error-rate"}],
        "effects": [
            {
                "capability": "compose.scale",
                "args": {"project_dir": "/srv/web", "service": "web", "replicas": 4},
            }
        ],
        "rationale": "错误率上升且 CPU 打满,先加副本。",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 正常路径:模型给得出,就照它的提
# ---------------------------------------------------------------------------


def test_valid_json_becomes_an_intent():
    intent = _propose(_planner(_answer()))
    assert intent.summary.startswith("把 web 扩到 4 副本")
    assert len(intent.effects) == 1
    assert intent.effects[0]["capability"] == "compose.scale"
    assert intent.effects[0]["args"]["replicas"] == 4


def test_fenced_json_is_still_read():
    """模型爱包围栏,这不是形状问题,是格式问题。"""
    intent = _propose(_planner("```json\n" + _answer() + "\n```"))
    assert len(intent.effects) == 1


def test_effects_pointing_at_a_declared_capability_survive():
    intent = _propose(_planner(_answer()))
    assert [e["capability"] for e in intent.effects] == ["compose.scale"]


# ---------------------------------------------------------------------------
# 不许编:每一种"答不上来"都要落到空 effects + 一句人话
# ---------------------------------------------------------------------------


def test_non_json_answer_declines():
    intent = _propose(_planner("我觉得应该扩容。"))
    assert intent.effects == ()
    assert "不猜" in intent.rationale


def test_mock_llm_answer_declines():
    """没有模型时 LLMService 返回一句占位文本——那也不能被当成意图。"""
    intent = _propose(_planner("Response to: 把 web 扩到 4 副本..."))
    assert intent.effects == ()
    assert "不猜" in intent.rationale


def test_wrong_shape_declines():
    intent = _propose(_planner(json.dumps({"effects": [{"capability": ""}]})))
    assert intent.effects == ()
    assert "不猜" in intent.rationale


def test_empty_menu_declines_without_calling_the_model():
    planner = _planner(_answer(), menu={})
    intent = _propose(planner)
    assert intent.effects == ()
    assert "没有插件声明" in intent.rationale
    assert planner.llm.calls == []


def test_undeclared_capability_is_dropped_and_said_out_loud():
    answer = _answer(
        effects=[
            {"capability": "compose.scale", "args": {"service": "web", "replicas": 4}},
            {"capability": "k8s.pod.evict", "args": {"pod": "web-1"}},
        ]
    )
    intent = _propose(_planner(answer))
    assert [e["capability"] for e in intent.effects] == ["compose.scale"]
    assert "k8s.pod.evict" in intent.rationale
    assert "剔除" in intent.rationale


def test_signal_without_title_is_a_caller_error():
    planner = _planner(_answer())
    try:
        asyncio.run(planner.propose({"signal": {}}))
    except ValueError as exc:
        assert "title" in str(exc)
    else:  # pragma: no cover - 走到这里说明校验没生效
        raise AssertionError("缺 title 应当直接报错,而不是猜一个意图")


def test_unknown_task_is_an_error_not_an_intent():
    planner = _planner(_answer())
    result = asyncio.run(planner.execute_task("something-else", {}))
    assert result["status"] == "error"


def test_execute_task_returns_a_plain_dict():
    planner = _planner(_answer())
    result = asyncio.run(planner.execute_task("propose", {"signal": SIGNAL}))
    assert set(result) == {"version", "summary", "evidence", "effects", "rationale"}


# ---------------------------------------------------------------------------
# 履历进得了提示词,也留得在账本里
# ---------------------------------------------------------------------------


HISTORY = [
    {"verdict": "rolled_back", "capability": "compose.scale", "binding": "prod", "reason": "验证未通过"},
    {"verdict": "kept", "capability": "compose.scale", "binding": "prod", "reason": "验证通过"},
]


def test_history_reaches_the_prompt():
    planner = _planner(_answer())
    _propose(planner, {"signal": SIGNAL, "history": HISTORY})
    user_prompt = planner.llm.calls[0][1]
    assert "账本结论" in user_prompt
    assert "rolled_back" in user_prompt


def test_history_is_recorded_as_evidence_not_just_prose():
    """判定用过什么证据,要留在单元里,不能只活在提示词里。"""
    intent = _propose(_planner(_answer()), {"signal": SIGNAL, "history": HISTORY})
    kinds = [e["kind"] for e in intent.evidence]
    assert "history" in kinds
    ref = next(e["ref"] for e in intent.evidence if e["kind"] == "history")
    assert "rolled_back" in ref and "kept" in ref


def test_no_history_means_no_history_evidence():
    intent = _propose(_planner(_answer()))
    assert all(e["kind"] != "history" for e in intent.evidence)


# ---------------------------------------------------------------------------
# 工作流:只有明确要证据的提供者,才让它付那一次查询
# ---------------------------------------------------------------------------


class StubProvider:
    def __init__(self, wants: bool) -> None:
        if wants:
            self.wants_history = True


class StubRegistry:
    def __init__(self, provider) -> None:
        self.provider = provider
        self.seen: dict | None = None

    def best_capability_provider(self, capability: str):
        return self.provider

    async def run_capability(self, capability: str, params: dict) -> dict:
        self.seen = params
        return {"version": 1, "summary": "测试", "evidence": [], "effects": [], "rationale": ""}


def _payload() -> dict:
    return {"signal": dict(SIGNAL), "tenant_slug": "tenant-a"}


def _wire(monkeypatch, provider, history):
    stub = StubRegistry(provider)
    monkeypatch.setattr(pipeline, "registry", stub)

    async def fake_history(tenant: str, limit: int = 20):
        return history

    monkeypatch.setattr(pipeline, "_recent_conclusions", fake_history)
    asyncio.run(pipeline._propose_intent_impl(_payload(), {}, []))
    return stub.seen


def test_provider_that_wants_history_gets_it(monkeypatch):
    seen = _wire(monkeypatch, StubProvider(wants=True), HISTORY)
    assert seen["history"] == HISTORY


def test_provider_that_does_not_ask_is_not_charged_for_the_query(monkeypatch):
    async def boom(tenant: str, limit: int = 20):
        raise AssertionError("没有人要用履历,不该去读账本")

    stub = StubRegistry(StubProvider(wants=False))
    monkeypatch.setattr(pipeline, "registry", stub)
    monkeypatch.setattr(pipeline, "_recent_conclusions", boom)
    asyncio.run(pipeline._propose_intent_impl(_payload(), {}, []))
    assert "history" not in stub.seen


def test_empty_history_is_left_out_entirely(monkeypatch):
    seen = _wire(monkeypatch, StubProvider(wants=True), [])
    assert "history" not in seen


# ---------------------------------------------------------------------------
# 声明:谁默认、菜单从哪来
# ---------------------------------------------------------------------------


def test_llm_provider_yields_to_the_rule_based_one_by_default():
    from engine.plugin_manager.manifest import Manifest

    llm = Manifest.from_yaml(AGENTS_DIR / "intent-llm" / "plugin.yaml")
    rule = Manifest.from_yaml(AGENTS_DIR / "intent-builder" / "plugin.yaml")
    assert llm.capabilities_priority["intent.propose"] < rule.capabilities_priority.get(
        "intent.propose", 0
    )


def test_planner_states_that_it_wants_history():
    """工作流靠这个属性决定要不要读账本;改了名字就会静默退化成没有证据。"""
    assert _plugin_module().LLMIntentPlanner.wants_history is True


def test_effect_declaration_keeps_its_argument_names():
    from engine.plugin_manager.manifest import Manifest

    manifest = Manifest.from_yaml(
        Path("plugins/builtin/actions/docker-compose/plugin.yaml")
    )
    decl = manifest.effects["compose.scale"]
    assert decl.execute_args == ("project_dir", "service", "replicas")
