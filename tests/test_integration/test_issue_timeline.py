# tests/test_integration/test_issue_timeline.py
"""议题时间线:三个状态怎么归一、一条线怎么拼。

聚合是纯函数,喂字典就能跑:不需要 Postgres,也不需要工作流。
"""

import asyncio

from engine.change_unit.timeline import (
    STATE_LANDED,
    STATE_RUNNING,
    STATE_WAITING,
    belongs,
    build_timeline,
    normalize_state,
    summarize_issue,
)

TOPIC = "acme/web#7"

SESSION = {
    "id": "s1",
    "workflow_id": "gwei-triage-abc",
    "status": "FIX_REQUESTED",
    "source": "issue",
    "started_at": "2026-11-14T10:00:00+00:00",
    "ended_at": "2026-11-14T10:02:00+00:00",
    "analysis": {
        "labels": ["bug"],
        "is_complete": True,
        "completeness_score": 0.8,
        "llm_analysis": "连接池耗尽\n建议先调大池子再看",
    },
}

INTENT = {
    "version": 1,
    "summary": "回评告诉运维连接池该调大",
    "rationale": "问题在配置,不在代码",
    "evidence": [{"kind": "issue", "ref": TOPIC}],
    "effects": [
        {"capability": "comment.create", "args": {"body": "把 pool 调到 50"}},
        {"capability": "compose.scale", "args": {"service": "web", "replicas": 3}},
    ],
    "topic": TOPIC,
    "workflow": "gwei-triage-abc:effects",
}


def _comment_row(**over):
    row = {
        "id": "u1",
        "created_at": "2026-11-14T10:00:30+00:00",
        "verdict": "kept",
        "reason": "验证通过,保持运行",
        "binding": "github",
        "tenant": "default",
        "incident_id": "gwei-triage-abc",
        "handle": "100",
        "window": {"unbounded": True, "source": "comment_present"},
        "intent": dict(INTENT),
        "effect": {
            "capability": "comment.create",
            "task": "create_comment",
            "args": {"repo": "acme/web", "issue_number": 7, "body": "hi"},
            "undo_task": "delete_comment",
            "undo_kind": "symmetric",
            "label": "在 Issue / PR 上发一条评论",
        },
        "facts": {"found": True, "gate": "不在自动收敛范围"},
    }
    row.update(over)
    return row


def _blocked_row(**over):
    row = _comment_row(
        id="u2",
        created_at="2026-11-14T10:00:40+00:00",
        verdict="blocked",
        reason="不在自动收敛范围:pr.open",
        handle=None,
        effect={
            "capability": "pr.open",
            "task": "open_pull",
            "args": {"repo": "acme/web", "head": "gwei/fix-7"},
            "undo_task": "close_pull",
            "undo_kind": "symmetric",
            "label": "开一个 PR",
        },
        facts={},
    )
    row.update(over)
    return row


def _issue(**over):
    issue = {
        "id": "0f0e0d0c",
        "number": 7,
        "title": "打开就崩",
        "body": "点开就 500",
        "labels": ["bug"],
        "status": "OPEN",
        "created_at": "2026-11-14T09:59:00+00:00",
    }
    issue.update(over)
    return issue


# -- 三个状态 ---------------------------------------------------------------


def test_blocked_waits_for_a_human():
    state, reason = normalize_state(changes=[_blocked_row()])
    assert state == STATE_WAITING
    assert "放行" in reason


def test_unknown_waits_because_nobody_knows():
    state, reason = normalize_state(changes=[_comment_row(verdict="unknown")])
    assert state == STATE_WAITING
    assert "下游核" in reason


def test_open_incident_is_waiting_because_it_may_be_stuck():
    state, reason = normalize_state(incident_open=True)
    assert state == STATE_WAITING
    assert "没收口" in reason


def test_pending_change_is_running():
    state, _ = normalize_state(changes=[_comment_row(verdict="pending")])
    assert state == STATE_RUNNING


def test_live_session_is_running():
    state, reason = normalize_state(session_running=True)
    assert state == STATE_RUNNING
    assert reason


def test_kept_is_landed_even_though_the_issue_is_still_open():
    """issue 一直是 OPEN:拿它盖过账本会把"已经改好"说成"还在等"。"""
    state, _ = normalize_state(changes=[_comment_row(verdict="kept")], issue_open=True)
    assert state == STATE_LANDED


def test_issue_without_changes_follows_its_own_status():
    assert normalize_state(changes=[], issue_open=True)[0] == STATE_WAITING
    assert normalize_state(changes=[], issue_open=False)[0] == STATE_LANDED


# -- 归属 -------------------------------------------------------------------


def test_belongs_by_topic_and_by_workflow():
    assert belongs(_comment_row(), TOPIC, set())
    # 声明式路径的 intent 上没有话题,靠 incident_id 落在本议题的执行上
    declared = {"intent": {"summary": "回评"}, "incident_id": "gwei-triage-abc"}
    assert belongs(declared, TOPIC, {"gwei-triage-abc"})
    assert not belongs({"intent": {"summary": "别的"}, "incident_id": "other"}, TOPIC, {"gwei-triage-abc"})


# -- 一条线 -----------------------------------------------------------------


def test_line_has_one_segment_per_stage():
    data = build_timeline(
        issue=_issue(),
        topic=TOPIC,
        sessions=[SESSION],
        changes=[_comment_row(), _blocked_row()],
    )
    assert data["state"] == STATE_WAITING
    assert data["topic"] == TOPIC and data["repo"] == "acme/web"
    assert len(data["rounds"]) == 1

    kinds = [s["kind"] for s in data["rounds"][0]["segments"]]
    # 两个单元共用一次意图:意图只出现一次,变更/结论各自出现
    assert kinds == [
        "signal",
        "diagnosis",
        "intent",
        "change",
        "verify",
        "conclusion",
        "change",
        "conclusion",
    ]


def test_segment_detail_is_the_engineering_decision():
    data = build_timeline(
        issue=_issue(), topic=TOPIC, sessions=[SESSION], changes=[_comment_row(), _blocked_row()]
    )
    segments = {s["kind"]: s for s in data["rounds"][0]["segments"]}

    # 打算做什么、为什么
    intent = segments["intent"]
    assert intent["summary"] == INTENT["summary"]
    assert intent["detail"]["rationale"] == INTENT["rationale"]
    # 打算做而没落成单元的候选要列出来
    assert [c["capability"] for c in intent["detail"]["candidates"]] == [
        "comment.create",
        "compose.scale",
    ]
    assert [c["capability"] for c in intent["detail"]["not_executed"]] == ["compose.scale"]

    # 证据层原文不加工
    assert intent["evidence"][0]["content"]["summary"] == INTENT["summary"]


def test_conclusion_says_whether_it_can_still_be_undone():
    data = build_timeline(
        issue=_issue(), topic=TOPIC, sessions=[SESSION], changes=[_comment_row()]
    )
    conclusion = [s for s in data["rounds"][0]["segments"] if s["kind"] == "conclusion"][0]
    assert conclusion["summary"] == "验证通过,保持运行"
    assert conclusion["detail"]["undoable"] is True
    # 放行 / 撤销要打在具体那个单元上,所以结论段必须带 id
    assert conclusion["detail"]["unit_id"] == "u1"


def test_irreversible_reason_names_the_step():
    row = _comment_row(
        id="u9",
        verdict="irreversible",
        reason="执行后没有句柄,无法兑现撤销",
        handle=None,
    )
    data = build_timeline(issue=_issue(), topic=TOPIC, changes=[row])
    conclusion = [s for s in data["rounds"][0]["segments"] if s["kind"] == "conclusion"][0]
    assert "没有句柄" in conclusion["summary"]
    assert conclusion["detail"]["undoable"] is False


def test_no_changes_still_returns_a_timeline():
    data = build_timeline(issue=_issue(), topic=TOPIC)
    assert data["rounds"] == []
    assert data["state"] == STATE_WAITING
    assert data["state_reason"] == "议题还开着,系统没有产生变更"


def test_each_round_keeps_its_own_conclusion():
    later = {
        "id": "s2",
        "workflow_id": "gwei-fix-xyz",
        "status": "FIX_REQUESTED",
        "source": "comment",
        "started_at": "2026-11-14T11:00:00+00:00",
        "ended_at": "2026-11-14T11:01:00+00:00",
        "analysis": {},
    }
    second = _comment_row(
        id="u3",
        created_at="2026-11-14T11:00:30+00:00",
        incident_id="gwei-fix-xyz",
        intent={"summary": "照人说的改", "workflow": "gwei-fix-xyz:effects"},
    )
    data = build_timeline(
        issue=_issue(),
        topic=TOPIC,
        sessions=[SESSION, later],
        changes=[_comment_row(), second],
    )
    assert [r["round"] for r in data["rounds"]] == [1, 2]
    # 第二轮是人叫出来的,信号说得出来
    assert data["rounds"][1]["segments"][0]["summary"] == "人在评论里叫了 @gwei"
    # 上一轮的结论不被新一轮覆盖
    assert data["rounds"][0]["verdicts"] == {"kept": 1}
    assert data["rounds"][1]["verdicts"] == {"kept": 1}


# -- 接口这一层 -------------------------------------------------------------


def test_route_wires_the_aggregation_together():
    """取数之外的部分:路径参数、租户口径、DTO 形状、截断标记。

    数据库那一段由门控用例 test_issue_timeline_api 覆盖;这里用替身跑通接线,
    所以没装 Postgres 也能发现"DTO 对不上聚合结果"这类错。
    """
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    import engine.api.routes.issues as issues_mod

    class _Ledger:
        async def latest(self, tenant=None, limit=None):
            return [_comment_row()]

    request = SimpleNamespace(state=SimpleNamespace(actor=None))
    with patch.object(
        issues_mod,
        "_load_issue",
        AsyncMock(return_value={
            "issue": _issue(),
            "repo": "acme/web",
            "tenant": "default",
            "sessions": [SESSION],
        }),
    ), patch.object(issues_mod, "create_ledger", lambda: _Ledger()), patch.object(
        issues_mod,
        "create_incident_store",
        lambda: SimpleNamespace(list=AsyncMock(return_value=[])),
    ), patch.object(issues_mod, "open_pull_on", AsyncMock(return_value=None)):
        dto = asyncio.run(issues_mod.issue_timeline(str(uuid.uuid4()), request))

    assert dto.topic == TOPIC
    assert dto.state == STATE_LANDED
    assert dto.branch is None
    assert dto.truncated is False
    assert len(dto.rounds) == 1
    assert dto.rounds[0].segments[0].kind == "signal"


def test_branch_is_passed_through_and_absent_when_unknown():
    branch = {"repo": "acme/web", "head": "gwei/fix-7", "pull": "12", "url": "https://x"}
    assert build_timeline(issue=_issue(), topic=TOPIC, branch=branch)["branch"] == branch
    assert build_timeline(issue=_issue(), topic=TOPIC)["branch"] is None

# -- 列表上的那一行 ---------------------------------------------------------


def test_summary_says_what_it_is_waiting_for():
    card = summarize_issue(
        issue=_issue(),
        topic=TOPIC,
        sessions=[SESSION],
        changes=[_comment_row(), _blocked_row()],
        branch={"head": "gwei/fix-7", "pull": "12"},
    )
    assert card["state"] == STATE_WAITING
    # 等你做什么要钉在具体一条单元上,不是一句"待处理"
    assert card["action"] == "approve"
    assert card["unit_id"] == "u2"
    assert card["rounds"] == 1
    assert card["waiting_since"] == "2026-11-14T10:00:40+00:00"
    assert card["branch"] == "gwei/fix-7"


def test_summary_of_a_kept_issue_says_it_can_still_be_undone():
    card = summarize_issue(issue=_issue(), topic=TOPIC, changes=[_comment_row()])
    assert card["state"] == STATE_LANDED
    assert card["action"] == ""
    assert card["undoable"] is True
    assert "验证通过" in card["conclusion"]


def test_summary_of_an_unknown_change_asks_a_human_to_look():
    card = summarize_issue(
        issue=_issue(), topic=TOPIC, changes=[_comment_row(verdict="unknown")]
    )
    assert card["state"] == STATE_WAITING
    assert card["action"] == "investigate"
    assert card["unit_id"] == "u1"


def test_summary_without_changes_follows_the_issue():
    card = summarize_issue(issue=_issue(), topic=TOPIC)
    assert card["state"] == STATE_WAITING
    assert card["action"] == ""
    assert card["rounds"] == 0

# -- 从界面发起一轮 ---------------------------------------------------------


def test_continue_payload_reuses_the_thread_and_keeps_the_issue_intact():
    import engine.api.routes.issues as issues_mod

    issue = {
        "github_id": 991,
        "number": 7,
        "title": "打开就崩",
        "body": "点开就 500",
    }
    payload = issues_mod.continue_payload(
        issue=issue,
        repo="acme/web",
        repo_id=42,
        tenant="default",
        topic=TOPIC,
        instruction="把副本调到 6,再跑一遍验证",
    )

    # 人在界面上说的话进 signal:事故把它记下来,时间线才说得出"第几轮说了什么"
    assert payload["signal"]["title"] == "把副本调到 6,再跑一遍验证"
    assert payload["signal"]["source"] == "console"
    # 一轮继续改不是重写这条议题:标题与正文取议题自己的
    assert payload["title"] == "打开就崩"
    assert payload["body"] == "点开就 500"
    # 分支沿用的凭据是话题,不是这里另挑一个分支
    assert payload["topic"] == TOPIC
    assert payload["issue_number"] == 7

def test_a_round_carries_what_it_changed():
    """轮次上要说得清这一轮改了哪些文件,行数由平台数。"""
    incident = {
        "id": "gwei-triage-abc",
        "topic": TOPIC,
        "status": "closed",
        "started_at": "2026-11-14T10:00:00+00:00",
        "finished_at": "2026-11-14T10:02:10+00:00",
        "summary": "",
        "diff": [{"path": "api/pool.py", "added": 30, "removed": 0, "status": "added"}],
    }
    data = build_timeline(
        issue=_issue(),
        topic=TOPIC,
        sessions=[SESSION],
        incidents=[incident],
        changes=[_comment_row()],
    )
    files = data["rounds"][0]["diff"]
    assert [f["path"] for f in files] == ["api/pool.py"]
    assert files[0]["added"] == 30

def test_skipped_candidates_carry_the_reason():
    """打算做而没做的那几个,要说得出为什么——名单不算答案。"""
    intent = {
        **INTENT,
        "skipped": [{"capability": "compose.scale", "reason": "没有提供者声明这个能力: x"}],
    }
    data = build_timeline(issue=_issue(), topic=TOPIC, changes=[_comment_row(intent=intent)])
    seg = [s for s in data["rounds"][0]["segments"] if s["kind"] == "intent"][0]
    assert seg["detail"]["not_executed"] == [
        {"capability": "compose.scale", "reason": "没有提供者声明这个能力: x"}
    ]


def test_verify_segment_says_what_was_checked():
    """查了什么、期望什么:来自声明,随单元落账,读的时候不依赖插件还在不在。"""
    effect = {
        **_comment_row()["effect"],
        "verify": [{"query": "comment_exists", "expect": "true"}],
    }
    data = build_timeline(issue=_issue(), topic=TOPIC, changes=[_comment_row(effect=effect)])
    seg = [s for s in data["rounds"][0]["segments"] if s["kind"] == "verify"][0]
    assert seg["detail"]["rules"] == [{"query": "comment_exists", "expect": "true"}]
    assert seg["detail"]["returned"] == {"found": True}

def test_a_round_that_did_nothing_still_says_why():
    """候选全被放弃时没有单元可读,证据只剩事故上记着的那份意图。"""
    incident = {
        "id": "gwei-alert-1",
        "topic": TOPIC,
        "status": "closed",
        "started_at": "2026-11-14T12:00:00+00:00",
        "finished_at": "2026-11-14T12:00:30+00:00",
        "summary": "想把 pool_max 调大",
        "intent": {
            "summary": "想把 pool_max 调大",
            "effects": [{"capability": "config.set", "args": {"key": "pool_max"}}],
            "skipped": [
                {"capability": "config.set", "reason": "没有提供者声明这个能力: config.set"}
            ],
        },
    }
    data = build_timeline(issue=_issue(), topic=TOPIC, incidents=[incident])

    assert len(data["rounds"]) == 1
    segments = data["rounds"][0]["segments"]
    assert [s["kind"] for s in segments] == ["signal", "intent"]
    assert segments[1]["summary"] == "想把 pool_max 调大"
    assert segments[1]["detail"]["not_executed"] == [
        {"capability": "config.set", "reason": "没有提供者声明这个能力: config.set"}
    ]
