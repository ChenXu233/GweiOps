# engine/change_unit/timeline.py
"""议题时间线 —— 一个议题的全部证据,按发生顺序排成一条线。

界面只服务一件事:把议题处理掉。处理它需要两样东西:此刻要不要人,以及**当时
到底发生了什么**。前者收成三个状态,后者就是这条线。两者都在这里算,前端不再
自己拼——猜出来的状态迟早会跟账本说反。

三个状态只在原词之外再给一层归一,原词仍原样留着给账本页:用户不需要先学会
七种结论的区别才能干活。

线上的每一段都是两层:summary 是一句人话,detail 是工程决策要点(常驻不折叠),
evidence 是存下来的原文(默认收起)。两条规矩:**摘要层不省略信息类别**,一段
人话下面必须点得到原文;**证据层不做二次加工**,存了什么显示什么,截断要标出来。

这一段缺什么就少一段。缺的本身就是信息,但不给它编一句"已完成分析"。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from .undo import undo_state

STATE_WAITING = "waiting"
STATE_RUNNING = "running"
STATE_LANDED = "landed"

SEG_SIGNAL = "signal"
SEG_DIAGNOSIS = "diagnosis"
SEG_INTENT = "intent"
SEG_CHANGE = "change"
SEG_VERIFY = "verify"
SEG_CONCLUSION = "conclusion"

# 系统正在做,没人要等
_BUSY_VERDICTS = ("pending",)
# 已经有结论了
_LANDED_VERDICTS = ("kept", "rolled_back", "irreversible", "vetoed", "failed")
# 执行之后真的走到验证的两种。其余结论要么没碰下游,要么连句柄都没有。
_VERIFIED = ("kept", "rolled_back")

# facts 里这些键是平台自己的簿记,不是"下游返回了什么"
_BOOKKEEPING = (
    "error",
    "gate",
    "authorized_by",
    "blocked_reason",
    "approval_reason",
    "vetoed_by",
    "rolled_back_by",
)

_SIGNAL_LINES = {
    "issue": "议题被投进来,开始分析",
    "comment": "人在评论里叫了 @gwei",
    "merge": "一次合并被投进来",
}

_TEXT_LIMIT = 4000


def _clip(value: str, limit: int = _TEXT_LIMIT) -> tuple[str, bool]:
    text = value or ""
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n…(已截断)", True


def _lead(value: Any, limit: int = 80) -> str:
    """一句话:取第一行,过长截断。"""
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def _moment(value: Any) -> datetime:
    """排序用。解析不了就当最早——排错位置好过抛出去。"""
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _evidence(label: str, content: Any, kind: str = "json") -> dict[str, Any]:
    if isinstance(content, str):
        text, truncated = _clip(content)
        return {"label": label, "kind": kind, "content": text, "truncated": truncated}
    return {"label": label, "kind": kind, "content": content, "truncated": False}


def _verdicts(changes: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in changes:
        verdict = str(row.get("verdict") or "")
        if verdict:
            counts[verdict] = counts.get(verdict, 0) + 1
    return counts


def normalize_state(
    *,
    changes: Iterable[dict[str, Any]] = (),
    issue_open: bool = True,
    session_running: bool = False,
    incident_open: bool = False,
) -> tuple[str, str]:
    """把七种结论与 issue 状态收成三个状态之一,并说清为什么。

    优先级就是"谁在拦着":有人要等的先报;没人要等但还在动的算在跑;都停了才算
    落了。incident 开着没收口排在前面——它可能卡住了,而卡住是等人,不是"在跑"。

    issue 状态只在**没有任何变更**时才有话语权。平台不改 issue.status,它永远是
    OPEN;拿它盖过账本会把"已经改好"说成"还在等",那正是要消灭的歧义。
    """
    counts = _verdicts(changes)

    # 停在这两个结论上、不动就没有下文:要么等人放行,要么人去下游核。
    if counts.get("blocked"):
        return STATE_WAITING, f"{counts['blocked']} 个变更在等你放行"
    if counts.get("unknown"):
        return STATE_WAITING, f"{counts['unknown']} 个变更不知道动没动,要去下游核"
    if incident_open:
        return STATE_WAITING, "有一场开了没收口,可能卡住了"
    busy = sum(counts.get(v, 0) for v in _BUSY_VERDICTS)
    if busy:
        return STATE_RUNNING, f"{busy} 个变更正在执行"
    if session_running:
        return STATE_RUNNING, "执行还在跑"

    settled = sum(counts.get(v, 0) for v in _LANDED_VERDICTS)
    if settled:
        return STATE_LANDED, f"{settled} 个变更已有结论,没有要等的"
    if issue_open:
        return STATE_WAITING, "议题还开着,系统没有产生变更"
    return STATE_LANDED, "议题已关闭"


def _session_key(session: dict[str, Any]) -> str:
    return str(session.get("workflow_id") or "") or (
        f"session:{session.get('id') or ''}" if session.get("id") else ""
    )


def belongs(row: dict[str, Any], topic: str, keys: set[str]) -> bool:
    """这一行账是不是这个议题的。

    两条路并着走:intent 上记着话题的,以及 incident_id 落在本议题某次执行上的。
    只认 incident_id 会漏掉发布这类"没有会话、也没有事故行"的执行——它们唯一
    连得上议题的凭据就是自己写在 intent 上的话题。
    """
    intent = row.get("intent")
    if topic and isinstance(intent, dict) and str(intent.get("topic") or "") == topic:
        return True
    incident_id = str(row.get("incident_id") or "")
    return bool(incident_id) and incident_id in keys


def _bucket(
    rounds: dict[str, dict[str, Any]], key: str, at: str
) -> dict[str, Any]:
    found = rounds.get(key)
    if found is None:
        found = {
            "key": key,
            "at": at,
            "finished_at": "",
            "session": None,
            "incident": None,
            "changes": [],
        }
        rounds[key] = found
    elif at and (not found["at"] or _moment(at) < _moment(found["at"])):
        found["at"] = at
    return found


def _group_rounds(
    sessions: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    changes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """一轮 = 一次执行。同一次执行的会话、事故、变更落在同一个桶里。"""
    rounds: dict[str, dict[str, Any]] = {}

    for session in sessions:
        key = _session_key(session)
        if key:
            _bucket(rounds, key, str(session.get("started_at") or ""))["session"] = session
    for incident in incidents:
        key = str(incident.get("id") or "")
        if key:
            bucket = _bucket(rounds, key, str(incident.get("started_at") or ""))
            bucket["incident"] = incident
            bucket["finished_at"] = str(incident.get("finished_at") or "")
    for row in changes:
        key = str(row.get("incident_id") or "")
        intent = row.get("intent")
        if not key and isinstance(intent, dict):
            key = str(intent.get("workflow") or "")
        bucket = _bucket(rounds, key, str(row.get("created_at") or ""))
        bucket["changes"].append(row)

    for bucket in rounds.values():
        session = bucket["session"] or {}
        bucket["finished_at"] = bucket["finished_at"] or str(session.get("ended_at") or "")
        bucket["changes"].sort(key=lambda row: _moment(row.get("created_at")))
        bucket["summary"] = str((bucket["incident"] or {}).get("summary") or "")

    return sorted(rounds.values(), key=lambda b: (_moment(b["at"]), b["key"]))


def _signal_segment(item: dict[str, Any], add) -> None:
    incident = item["incident"]
    if incident:
        source = str(incident.get("signal_source") or "")
        title = str(incident.get("signal_title") or "")
        add(
            SEG_SIGNAL,
            str(incident.get("started_at") or ""),
            f"{source} 报来:{title}" if source else title,
            {"source": source, "topic": str(incident.get("topic") or "")},
            [
                _evidence(
                    "报来的信号",
                    {
                        "source": source,
                        "title": title,
                        "topic": str(incident.get("topic") or ""),
                        "started_at": str(incident.get("started_at") or ""),
                    },
                )
            ],
        )
        return

    session = item["session"]
    if not session:
        return
    source = str(session.get("source") or "")
    add(
        SEG_SIGNAL,
        str(session.get("started_at") or ""),
        _SIGNAL_LINES.get(source, "议题被投进来"),
        {
            "source": source,
            "session": str(session.get("id") or ""),
            "workflow": _session_key(session),
        },
    )


def _diagnosis_segment(item: dict[str, Any], add) -> None:
    session = item["session"] or {}
    analysis = session.get("analysis")
    if not isinstance(analysis, dict) or not analysis:
        return

    labels = [str(label) for label in (analysis.get("labels") or [])]
    raw = str(analysis.get("llm_analysis") or "")
    summary = _lead(raw) or ("判定标签:" + "、".join(labels) if labels else "分析完成")

    detail: dict[str, Any] = {}
    for key in ("labels", "is_complete", "completeness_score"):
        if analysis.get(key) is not None:
            detail[key] = analysis[key]

    evidence = []
    if raw:
        evidence.append(_evidence("分析原文", raw, kind="text"))
    add(SEG_DIAGNOSIS, str(session.get("started_at") or ""), summary, detail, evidence)


def _intent_groups(changes: list[dict[str, Any]]) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """按意图分组:一次意图落成几个变更单元,读的时候还是一件事。

    agent 走出口时每次调用一个意图,声明式路径一次意图落多个单元,两种都收得住。
    """
    groups: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    index: dict[tuple[str, str, str], int] = {}
    for row in changes:
        intent = row.get("intent")
        intent = intent if isinstance(intent, dict) else {}
        key = (
            str(intent.get("summary") or ""),
            str(intent.get("rationale") or ""),
            str(intent.get("workflow") or ""),
        )
        if key not in index:
            index[key] = len(groups)
            groups.append((intent, []))
        groups[index[key]][1].append(row)
    return groups


def _candidates(intent: dict[str, Any]) -> list[dict[str, Any]]:
    raw = intent.get("effects")
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("capability"):
            continue
        args = item.get("args")
        out.append(
            {
                "capability": str(item["capability"]),
                "args": args if isinstance(args, dict) else {},
            }
        )
    return out


def _not_executed(
    intent: dict[str, Any], candidates: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """打算做、但没落成变更单元的那几个,以及为什么没做。

    理由由工作流在建单元之前写进 intent——那时才知道有没有提供者、有没有被扩展点
    拦下。老账本行没有这个键,退回"候选减去已落的单元"算一张名单:名单里没有
    理由,不能假装有。
    """
    recorded = intent.get("skipped")
    if isinstance(recorded, list) and recorded:
        return {
            "not_executed": [
                {
                    "capability": str(item.get("capability") or ""),
                    "reason": str(item.get("reason") or ""),
                }
                for item in recorded
                if isinstance(item, dict) and item.get("capability")
            ]
        }

    left: dict[str, int] = {}
    for item in candidates:
        left[item["capability"]] = left.get(item["capability"], 0) + 1
    for row in rows:
        effect = row.get("effect")
        capability = str(effect.get("capability") or "") if isinstance(effect, dict) else ""
        if left.get(capability):
            left[capability] -= 1

    missed = []
    for item in candidates:
        if left.get(item["capability"], 0) > 0:
            left[item["capability"]] -= 1
            missed.append(item)
    return {"not_executed": missed} if missed else {}


def _intent_segment(intent: dict[str, Any], rows: list[dict[str, Any]], at: str, add) -> None:
    detail: dict[str, Any] = {}
    if intent.get("rationale"):
        detail["rationale"] = intent["rationale"]
    if intent.get("tool"):
        detail["tool"] = intent["tool"]
    if intent.get("by"):
        detail["by"] = intent["by"]

    candidates = _candidates(intent)
    if candidates:
        detail["candidates"] = candidates
        detail.update(_not_executed(intent, candidates, rows))

    evidence = [_evidence("意图原文", intent)]
    if intent.get("evidence"):
        evidence.append(_evidence("依据", intent["evidence"]))

    add(
        SEG_INTENT,
        at,
        str(intent.get("summary") or "") or "没有记录意图",
        detail,
        evidence,
    )


def _change_segment(row: dict[str, Any], add) -> None:
    effect = row.get("effect")
    effect = effect if isinstance(effect, dict) else {}
    capability = str(effect.get("capability") or "")
    label = str(effect.get("label") or "") or capability
    binding = str(row.get("binding") or "")

    detail: dict[str, Any] = {}
    for key in ("capability", "task", "args", "undo_task", "undo_kind"):
        value = effect.get(key)
        if value not in (None, "", {}):
            detail[key] = value
    if binding:
        detail["binding"] = binding

    add(
        SEG_CHANGE,
        str(row.get("created_at") or ""),
        f"{label} → {binding}" if binding else label,
        detail,
        [_evidence("变更原文", row)],
    )


def _verify_segment(row: dict[str, Any], add) -> None:
    """验证:下游返回了什么、这次算过没过。

    只在真的走到验证时才有这一段。过了没过由结论反推——kept 是验证通过才写下的,
    rolled_back 在执行之后只可能是验证没过,所以这不是猜。
    """
    verdict = str(row.get("verdict") or "")
    facts = row.get("facts")
    facts = facts if isinstance(facts, dict) else {}
    error = facts.get("error")
    error = error if isinstance(error, dict) else {}

    returned = {k: v for k, v in facts.items() if k not in _BOOKKEEPING}
    verify_failed = str(error.get("stage") or "") == "verify"
    # 只有真的走到验证才说验证:没有句柄、窗口读不到那几种不可逆,验证根本没跑过。
    if verdict not in _VERIFIED and not verify_failed:
        return

    if verify_failed:
        summary = "验证时下游报错"
    elif verdict == "kept":
        summary = "验证通过"
    else:
        summary = "验证未通过"

    detail: dict[str, Any] = {}
    # 查了什么、期望什么:来自插件声明,随单元落账,读的时候不依赖插件还在不在。
    effect = row.get("effect")
    rules = effect.get("verify") if isinstance(effect, dict) else None
    if rules:
        detail["rules"] = rules
    if returned:
        detail["returned"] = returned
    if error:
        detail["error"] = error

    add(
        SEG_VERIFY,
        str(row.get("created_at") or ""),
        summary,
        detail,
        [_evidence("下游返回", returned or facts)],
    )


def _conclusion_segment(row: dict[str, Any], add) -> None:
    """结论:保留 / 回滚 / 阻断 / 不知道,以及此刻还撤不撤得回来。

    不可逆必须说清是哪一步让它不可逆 —— 理由是引擎写下的那一句,它本来就是
    "没有句柄 / 读不到窗口 / 撤销也失败"之一,这里不重写。
    """
    state = undo_state(row)
    detail: dict[str, Any] = {
        # 动作打在这个 id 上:界面不必从证据里翻账本行才知道自己该放行哪一个。
        "unit_id": str(row.get("id") or ""),
        "verdict": str(row.get("verdict") or ""),
        "undoable": state.undoable,
        "undo_reason": state.reason,
        # 空字符串 = 不会过期(对称撤销)。界面据此说"还能撤到几点"。
        "undo_expires_at": state.expires_at,
    }
    if row.get("window") is not None:
        detail["window"] = row.get("window")
    if row.get("handle"):
        detail["handle"] = row["handle"]

    summary = str(row.get("reason") or "") or f"结论:{row.get('verdict') or '未知'}"
    add(
        SEG_CONCLUSION,
        str(row.get("created_at") or ""),
        summary,
        detail,
        [_evidence("账本这一行", row)],
    )


def _idle_segment(item: dict[str, Any], add) -> None:
    """一个候选都没落下的一轮:说清本打算做什么、为什么都没做。

    这一轮没有单元可读,证据只有事故上记着的那份意图。空着不说,界面就只能显示
    信号和诊断,像是"想了一半停了"。
    """
    intent = (item["incident"] or {}).get("intent")
    if not isinstance(intent, dict) or not intent:
        return

    candidates = _candidates(intent)
    detail: dict[str, Any] = {}
    if candidates:
        detail["candidates"] = candidates
    detail.update(_not_executed(intent, candidates, []))
    add(
        SEG_INTENT,
        str((item["incident"] or {}).get("started_at") or ""),
        str(intent.get("summary") or "") or "这一轮没有任何候选被执行",
        detail,
        [_evidence("意图原文", intent)],
    )


def _segments(item: dict[str, Any], number: int) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []

    def add(
        kind: str,
        at: str,
        summary: str,
        detail: dict[str, Any] | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> None:
        segments.append(
            {
                "id": f"r{number}.{kind}.{len(segments)}",
                "kind": kind,
                "at": at or "",
                "summary": summary,
                "detail": detail or {},
                "evidence": evidence or [],
            }
        )

    _signal_segment(item, add)
    _diagnosis_segment(item, add)
    for intent, rows in _intent_groups(item["changes"]):
        _intent_segment(intent, rows, str(rows[0].get("created_at") or ""), add)
        for row in rows:
            _change_segment(row, add)
            _verify_segment(row, add)
            _conclusion_segment(row, add)
    if not item["changes"]:
        _idle_segment(item, add)
    return segments


def build_timeline(
    *,
    issue: dict[str, Any],
    topic: str = "",
    changes: Iterable[dict[str, Any]] = (),
    sessions: Iterable[dict[str, Any]] = (),
    incidents: Iterable[dict[str, Any]] = (),
    branch: dict[str, Any] | None = None,
    truncated: bool = False,
) -> dict[str, Any]:
    """一个议题的时间线。没有变更也返回:那是"还没发生",不是"查不到"。"""
    session_rows = [s for s in sessions if isinstance(s, dict)]
    incident_rows = [
        row
        for row in incidents
        if isinstance(row, dict) and (not topic or str(row.get("topic") or "") == topic)
    ]
    keys = {_session_key(session) for session in session_rows}
    keys |= {str(row.get("id") or "") for row in incident_rows}
    keys.discard("")

    picked = [row for row in changes if isinstance(row, dict) and belongs(row, topic, keys)]
    grouped = _group_rounds(session_rows, incident_rows, picked)

    rounds = [
        {
            "round": number,
            "key": item["key"],
            "at": item["at"],
            "finished_at": item["finished_at"],
            "summary": item["summary"],
            "verdicts": _verdicts(item["changes"]),
            # 这一轮改了哪些文件:事故里记着,平台从工作区数的。
            "diff": list((item["incident"] or {}).get("diff") or []),
            "segments": _segments(item, number),
        }
        for number, item in enumerate(grouped, start=1)
    ]

    state, reason = normalize_state(
        changes=picked,
        issue_open=str(issue.get("status") or "").upper() == "OPEN",
        session_running=any(not session.get("ended_at") for session in session_rows),
        incident_open=any(str(row.get("status") or "") == "open" for row in incident_rows),
    )

    return {
        "id": str(issue.get("id") or ""),
        "number": int(issue.get("number") or 0),
        "title": str(issue.get("title") or ""),
        "topic": topic,
        "repo": topic.rsplit("#", 1)[0] if "#" in topic else "",
        "state": state,
        "state_reason": reason,
        "branch": branch or None,
        "rounds": rounds,
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# 议题板:一张列表上的三个状态
# ---------------------------------------------------------------------------


def _updated_at(
    changes: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    fallback: str = "",
) -> str:
    stamps = [str(row.get("created_at") or "") for row in changes]
    stamps += [str(s.get("started_at") or "") for s in sessions]
    stamps += [str(s.get("ended_at") or "") for s in sessions]
    stamps += [str(i.get("started_at") or "") for i in incidents]
    stamps = [s for s in stamps if s]
    return max(stamps, key=_moment) if stamps else fallback


def summarize_issue(
    *,
    issue: dict[str, Any],
    topic: str = "",
    changes: Iterable[dict[str, Any]] = (),
    sessions: Iterable[dict[str, Any]] = (),
    incidents: Iterable[dict[str, Any]] = (),
    branch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """列表要的那一行:三个状态、等你做什么、几轮、一句话结论。

    与 build_timeline 读同一份证据、走同一个 normalize_state——列表和详情说
    不一样的话,是最难查的那种 bug。
    """
    session_rows = [s for s in sessions if isinstance(s, dict)]
    incident_rows = [
        row
        for row in incidents
        if isinstance(row, dict) and (not topic or str(row.get("topic") or "") == topic)
    ]
    keys = {_session_key(session) for session in session_rows}
    keys |= {str(row.get("id") or "") for row in incident_rows}
    keys.discard("")

    picked = [row for row in changes if isinstance(row, dict) and belongs(row, topic, keys)]
    picked.sort(key=lambda row: _moment(row.get("created_at")))

    state, reason = normalize_state(
        changes=picked,
        issue_open=str(issue.get("status") or "").upper() == "OPEN",
        session_running=any(not session.get("ended_at") for session in session_rows),
        incident_open=any(str(row.get("status") or "") == "open" for row in incident_rows),
    )

    # 等你做什么:钉在具体一条单元上,点进详情就能直接动手。
    action, unit_id = "", ""
    for verdict, name in (("blocked", "approve"), ("unknown", "investigate")):
        hit = next((row for row in picked if str(row.get("verdict") or "") == verdict), None)
        if hit is not None:
            action, unit_id = name, str(hit.get("id") or "")
            break

    waiting = [r for r in picked if str(r.get("verdict") or "") in ("blocked", "unknown")]
    waiting_since = str(waiting[0].get("created_at") or "") if waiting else ""

    rounds = {str(row.get("incident_id") or "") for row in picked}
    rounds |= {_session_key(session) for session in session_rows}
    rounds.discard("")

    last = picked[-1] if picked else None
    undoable, undo_reason = False, ""
    if last is not None:
        state_of_last = undo_state(last)
        undoable, undo_reason = state_of_last.undoable, state_of_last.reason

    return {
        "id": str(issue.get("id") or ""),
        "number": int(issue.get("number") or 0),
        "title": str(issue.get("title") or ""),
        "repo": topic.rsplit("#", 1)[0] if "#" in topic else "",
        "topic": topic,
        "state": state,
        "state_reason": reason,
        "action": action,
        "unit_id": unit_id,
        "rounds": len(rounds),
        "waiting_since": waiting_since,
        "updated_at": _updated_at(picked, session_rows, incident_rows, str(issue.get("created_at") or "")),
        "conclusion": str((last or {}).get("reason") or ""),
        # 原词只在接口里走:列表要按它选文案,页面上不出现。
        "verdict": str((last or {}).get("verdict") or ""),
        "undoable": undoable,
        "undo_reason": undo_reason,
        "branch": str((branch or {}).get("head") or ""),
        "pull": str((branch or {}).get("pull") or ""),
    }


__all__ = [
    "build_timeline",
    "summarize_issue",
    "belongs",
    "normalize_state",
    "STATE_WAITING",
    "STATE_RUNNING",
    "STATE_LANDED",
    "SEG_SIGNAL",
    "SEG_DIAGNOSIS",
    "SEG_INTENT",
    "SEG_CHANGE",
    "SEG_VERIFY",
    "SEG_CONCLUSION",
]