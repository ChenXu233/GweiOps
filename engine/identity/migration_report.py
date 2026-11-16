# engine/identity/migration_report.py
"""同一邮箱撞两个工作区时,那份清单。

拆表之前,`users` 按 (租户, 邮箱) 唯一 —— 同一个人被邀进第二个工作区时,那里会
有第二行:第二份密码、第二个"最后登录"。迁移 018 把同一个邮箱并成了一条
`persons` + 两条 `memberships`,并这一下需要一个判据:**这些都是同一个人吗**。

自动并是有风险的:两个工作区里各有一个 `ops@company.com`,可能是同一个人被两个
团队都请了进去,也可能根本是两个人(不同部门的公共邮箱)。这件事机器答不上来,
所以它是一份**清单**,每条都要有结论:

- `merged`:同一个人。保留这一条 person,两个工作区都是他的
- `kept`:不是同一个人(或暂时说不清)。各留一条 person,邮箱必须被改掉一个 ——
  `persons.email` 在整个部署里唯一,两条同邮箱的行放不进去

判据只有一条:清单里每一组都得有结论,而且能重新跑一遍复现同一份。迁移 018 已经
按"并"做过一次(数据量小、密码取最早那行),所以这份清单的用途是**回头核对**:
漏判的那一组会在 `git diff` 里以"两个工作区只剩一条成员关系"的形式露出来。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DECISIONS_FILE = Path("deploy/identity-merge.json")


MERGED = "merged"
KEPT = "kept"
VERDICTS = (MERGED, KEPT)


@dataclass(frozen=True)
class MergePlan:
    """清单里的一组:同一个邮箱,出现在哪几个工作区里。"""

    email: str
    workspaces: tuple[str, ...]
    # 每个工作区里那条成员关系的 display_name:判"是不是同一个人"最常看的就是它
    names: tuple[str, ...] = ()
    # 人给的结论。空 = 还没人看过
    verdict: str = ""
    note: str = ""

    @property
    def decided(self) -> bool:
        return self.verdict in VERDICTS

    def to_dict(self) -> dict:
        return {
            "email": self.email,
            "workspaces": list(self.workspaces),
            "names": list(self.names),
            "verdict": self.verdict,
            "note": self.note,
        }


@dataclass
class Report:
    """一份清单。`rows` 是一组一组的,`uncovered` 是判不了的。"""

    rows: list[MergePlan] = field(default_factory=list)

    @property
    def pending(self) -> list[MergePlan]:
        return [row for row in self.rows if not row.decided]

    @property
    def complete(self) -> bool:
        return not self.pending


def load_decisions(path: str | Path = DECISIONS_FILE) -> dict[str, dict]:
    """人写的结论。文件不在 = 一条结论都没有,清单因此不会"看起来做完了"。"""
    target = Path(path)
    if not target.exists():
        return {}
    raw = json.loads(target.read_text(encoding="utf-8"))
    entries = raw.get("decisions", raw) if isinstance(raw, dict) else {}
    out: dict[str, dict] = {}
    for email, value in entries.items():
        verdict = str((value or {}).get("verdict") or "").strip()
        if verdict not in VERDICTS:
            raise ValueError(f"{email}: 结论只能是 {' / '.join(VERDICTS)},收到 {verdict!r}")
        out[str(email).strip().lower()] = {
            "verdict": verdict,
            "note": str((value or {}).get("note") or ""),
        }
    return out


def apply_decisions(report_: Report, decisions: dict[str, dict]) -> Report:
    """把结论贴到清单上。没写结论的那几组仍然 pending。"""
    rows = []
    for row in report_.rows:
        found = decisions.get(row.email) or {}
        rows.append(
            MergePlan(
                email=row.email,
                workspaces=row.workspaces,
                names=row.names,
                verdict=str(found.get("verdict") or ""),
                note=str(found.get("note") or ""),
            )
        )
    return Report(rows=rows)


async def report() -> Report:
    """从库里读出"同一个邮箱出现在两个以上工作区"的那几组。

    拆表之后这件事只可能留在 `memberships` 里(一条 person 挂着两条成员关系)——
    那不是冲突,是**本来就这样**。真要看的是迁移前后有没有并错,所以这份清单按
    person 读:一条 person 挂着多个工作区,就是曾经撞过的那一组。
    """
    from sqlalchemy import select

    from engine.db import async_session_factory
    from engine.db.models import Membership, Person, Tenant

    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(Person.email, Tenant.slug, Membership.display_name)
                .join(Membership, Membership.person_id == Person.id)
                .join(Tenant, Tenant.id == Membership.tenant_id)
                .order_by(Person.email, Tenant.slug)
            )
        ).all()

    grouped: dict[str, list[tuple[str, str]]] = {}
    for email, slug, display_name in rows:
        grouped.setdefault(str(email), []).append((str(slug), str(display_name or "")))
    return Report(
        rows=[
            MergePlan(
                email=email,
                workspaces=tuple(slug for slug, _ in items),
                names=tuple(name for _, name in items),
            )
            for email, items in sorted(grouped.items())
            if len(items) > 1
        ]
    )


def render_report(report_: Report) -> str:
    """给人看的一页。没结论的那几组排在最前面 —— 它们才是要干活的地方。"""
    lines = ["# 一人多工作区:迁移审计清单", ""]
    if not report_.rows:
        lines.append("没有哪个邮箱出现在两个以上工作区里。")
        return "\n".join(lines)

    lines.append(f"共 {len(report_.rows)} 组,待判定 {len(report_.pending)} 组。")
    lines.append("")
    for row in sorted(report_.rows, key=lambda r: (r.decided, r.email)):
        mark = row.verdict or "待判定"
        lines.append(f"## {row.email} — {mark}")
        lines.append("")
        lines.append("| 工作区 | 那里叫的名字 |")
        lines.append("| --- | --- |")
        for slug, name in zip(row.workspaces, row.names):
            lines.append(f"| {slug} | {name} |")
        if row.note:
            lines.append("")
            lines.append(row.note)
        lines.append("")
    return "\n".join(lines)
