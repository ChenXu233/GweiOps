# tests/test_integration/test_identity_audit.py
"""一人多工作区的审计清单:每一组都得有结论,而且是可复跑的。

这里不碰库(读库那一段是 `scripts/identity_audit.py` 的事),验的是判据本身:
没结论就不是"做完了",结论写错要当场拒绝,同一份输入跑两遍输出一样。
"""

from __future__ import annotations

import json

import pytest

from engine.identity import (
    KEPT,
    MERGED,
    MergePlan,
    Report,
    apply_decisions,
    load_decisions,
    render_report,
)


def _report() -> Report:
    return Report(
        rows=[
            MergePlan(
                email="ops@example.com",
                workspaces=("acme", "beta"),
                names=("值班人", "值班人"),
            ),
            MergePlan(
                email="hr@example.com",
                workspaces=("acme", "beta"),
                names=("人事", "人事-beta"),
            ),
        ]
    )


def test_a_group_without_a_verdict_keeps_the_report_open():
    """空清单与"都判定过了"不是一回事 —— 这条是它能不能当验收用的分界。"""
    found = _report()
    assert not found.complete
    assert [row.email for row in found.pending] == ["ops@example.com", "hr@example.com"]


def test_every_group_must_have_a_verdict():
    found = apply_decisions(
        _report(),
        load_decisions_from(
            {
                "ops@example.com": {"verdict": MERGED, "note": "同一人"},
                "hr@example.com": {"verdict": KEPT, "note": "两个部门的公共邮箱,beta 那条已改名"},
            }
        ),
    )
    assert found.complete
    assert {row.verdict for row in found.rows} == {MERGED, KEPT}


def test_a_bad_verdict_is_refused_not_guessed(tmp_path):
    """写错结论就当没写是不行的:那会让"做完了"变成一个谎。"""
    target = tmp_path / "decisions.json"
    target.write_text(
        json.dumps({"decisions": {"ops@example.com": {"verdict": "maybe"}}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_decisions(target)


def test_the_same_input_renders_the_same_page():
    """待判定的排在前面,同一档内按邮箱排 —— 两份清单能逐行对上是"可复跑"的判据。"""
    first = render_report(apply_decisions(_report(), {}))
    second = render_report(apply_decisions(_report(), {}))
    assert first == second
    # 待判定的排在最前面,同一档内按邮箱排:两份清单能逐行对上才叫可复跑
    assert first.index("hr@example.com") < first.index("ops@example.com")


def test_a_decision_cannot_make_a_group_that_was_not_there():
    """结论是贴在清单上的,不是清单的来源:多写一条不会凭空多出一组。"""
    found = apply_decisions(
        _report(),
        {"ghost@example.com": {"verdict": MERGED, "note": "手滑写错了"}},
    )
    assert [row.email for row in found.rows] == ["ops@example.com", "hr@example.com"]
    assert not found.complete


def load_decisions_from(entries: dict) -> dict:
    return {
        email.lower(): {"verdict": value["verdict"], "note": value.get("note", "")}
        for email, value in entries.items()
    }
