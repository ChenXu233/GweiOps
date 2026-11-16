# engine/api/routes/issues.py
"""议题 —— 一条时间线装下它的全部证据。

议题是用户唯一要处理的对象:变更账本、执行记录、事故报告都是它的证据,不是与它
并列的工作对象。所以这里不按"账本 / 事故 / 执行"各出一个接口,而是按议题聚合。

三个状态 `state` 由后端给,前端不自己拼:拼出来的状态迟早会跟账本说反。
证据原文原样透出,聚合在 `engine/change_unit/timeline.py` 里做,这里只负责取数。
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import aliased

from engine.api.auth import require, tenant_scope
from engine.api.schemas import (
    ContinueRoundDTO,
    ContinuedDTO,
    IssueBoardDTO,
    IssueCardDTO,
    IssueTimelineDTO,
)
from engine.change_unit import create_ledger
from engine.change_unit.threads import open_pull_in, open_pull_on, topic_of
from engine.change_unit.timeline import build_timeline, summarize_issue
from engine.db import async_session_factory
from engine.db.models import AgentSession, Issue, Project, Tenant
from engine.incidents import create_incident_store
from engine.workflows.pipeline import fix_suggestion_workflow
from engine.workflows.queue import enqueue_workflow

router = APIRouter()
logger = logging.getLogger(__name__)

# 一次最多看这么多账本行与事故。超了如实标 truncated,不假装全看过了。
LEDGER_SCAN = 500
INCIDENT_SCAN = 200
# 三段在页面上的先后:等我 → 在跑 → 落了。
ORDER = ("waiting", "running", "landed")


async def _load_issue(wanted: UUID, scope: str | None) -> dict:
    """议题本体与它的执行记录。一次取完,后面不再握着会话。"""
    async with async_session_factory() as db:
        row = (
            await db.execute(
                select(Issue, Project, Tenant.slug)
                .join(Project, Issue.project_id == Project.id)
                .join(Tenant, Project.tenant_id == Tenant.id)
                .where(Issue.id == wanted)
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Issue not found")
        issue, project, slug = row

        # 令牌声明的租户优先:不是这个租户的议题按不存在回答,不说"有但不能看"。
        if scope and slug != scope:
            raise HTTPException(status_code=404, detail="Issue not found")

        sessions = (
            (
                await db.execute(
                    select(AgentSession)
                    .where(AgentSession.issue_id == issue.id)
                    .order_by(AgentSession.started_at)
                )
            )
            .scalars()
            .all()
        )

        return {
            "issue": {
                "id": str(issue.id),
                "github_id": issue.github_id,
                "number": issue.number,
                "title": issue.title,
                "body": issue.body or "",
                "labels": list(issue.labels or []),
                "status": issue.status,
                "created_at": issue.created_at.isoformat() if issue.created_at else "",
            },
            "repo": project.name,
            "repo_slug": project.slug,
            "repo_id": project.github_id,
            "tenant": slug,
            "sessions": [_session_row(s) for s in sessions],
        }


def _session_row(session: AgentSession) -> dict:
    """一次执行。workflow_id 是它跟账本行对上的凭据:账本里的 incident_id 就是它。"""
    state = session.state if isinstance(session.state, dict) else {}
    analysis = state.get("analysis")
    return {
        "id": str(session.id),
        "workflow_id": str(state.get("workflow_id") or ""),
        "status": session.status,
        "source": str(state.get("source") or ""),
        "analysis": analysis if isinstance(analysis, dict) else {},
        "started_at": session.started_at.isoformat() if session.started_at else "",
        "ended_at": session.ended_at.isoformat() if session.ended_at else "",
    }


@router.get("/api/issues/{issue_id}/timeline")
async def issue_timeline(
    issue_id: str, request: Request, tenant: str | None = None
) -> IssueTimelineDTO:
    """一个议题的完整时间线。还没有变更也返回:那是"还没发生",不是"查不到"。"""
    require(request, "changes.read")
    scope = tenant_scope(request, tenant)
    try:
        wanted = UUID(issue_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Issue not found") from None

    loaded = await _load_issue(wanted, scope)
    topic = topic_of(loaded["repo"], loaded["issue"]["number"])

    incidents = await create_incident_store().list(
        tenant=loaded["tenant"], limit=INCIDENT_SCAN
    )
    ledger = create_ledger()
    changes = await ledger.latest(tenant=loaded["tenant"], limit=LEDGER_SCAN)
    # 话题上此刻还开着的那个 PR:接着改就是接着它的分支。没有就是没有。
    branch = await open_pull_on(ledger, loaded["tenant"], topic)

    return IssueTimelineDTO.model_validate(
        build_timeline(
            issue=loaded["issue"],
            topic=topic,
            changes=changes,
            sessions=loaded["sessions"],
            incidents=incidents,
            branch=branch,
            truncated=len(incidents) >= INCIDENT_SCAN or len(changes) >= LEDGER_SCAN,
        )
    )


@router.get("/api/board")
async def issue_board(
    request: Request,
    tenant: str | None = None,
    project: str | None = None,
    repo: str | None = None,
    limit: int = 100,
) -> IssueBoardDTO:
    """议题板:首页那一张列表。

    一块板子三个段,判据与详情页同源(`normalize_state`)——列表说"在跑"、
    点进去说"落了"是最难查的那类 bug。三段各按自己的顺序排:等着的按等得
    最久在前,跑着与落了的按最新在前。

    `project` 与 `repo` 是范围闸,不是两段导航:板子始终只有一个,收窄的是它看
    的范围 —— 整个工作区 → 某个项目 → 某个仓库。两档都给时仓库那个说了算:它更窄,
    而它能被选到,本身就说明它属于当前这一档。
    """
    require(request, "changes.read")
    scope = tenant_scope(request, tenant)

    parent = aliased(Project)
    async with async_session_factory() as db:
        stmt = (
            select(Issue, Project.name, Tenant.slug)
            .join(Project, Issue.project_id == Project.id)
            .join(Tenant, Project.tenant_id == Tenant.id)
            .order_by(Issue.created_at.desc())
            .limit(max(0, limit))
        )
        if scope:
            stmt = stmt.where(Tenant.slug == scope)
        if repo:
            # 仓库档:slug 是来源前缀的写法(github-acme-api),与 /api/repos 同一栏
            stmt = stmt.where(Project.slug == repo)
        elif project:
            # 项目档:仓库行的 parent_id 指向项目那一行
            stmt = stmt.join(parent, parent.id == Project.parent_id).where(parent.slug == project)
        rows = (await db.execute(stmt)).all()
        if not rows:
            return IssueBoardDTO(items=[], counts={"waiting": 0, "running": 0, "landed": 0})
        sessions = (
            (
                await db.execute(
                    select(AgentSession)
                    .where(AgentSession.issue_id.in_([issue.id for issue, _, _ in rows]))
                    .order_by(AgentSession.started_at)
                )
            )
            .scalars()
            .all()
        )

    by_issue: dict[str, list[dict]] = {}
    for session in sessions:
        by_issue.setdefault(str(session.issue_id), []).append(_session_row(session))

    ledger = create_ledger()
    incident_store = create_incident_store()
    # 账本与事故按租户一次取回:selfhost 只有一个租户,多租户下也不会按议题重复读。
    evidence: dict[str, tuple[list[dict], list[dict]]] = {}
    for slug in {slug for _, _, slug in rows}:
        evidence[slug] = (
            await ledger.latest(tenant=slug, limit=LEDGER_SCAN),
            await incident_store.list(tenant=slug, limit=INCIDENT_SCAN),
        )

    items = []
    for issue, project, slug in rows:
        changes, incidents = evidence[slug]
        topic = topic_of(project, issue.number)
        items.append(
            IssueCardDTO.model_validate(
                summarize_issue(
                    issue={
                        "id": str(issue.id),
                        "number": issue.number,
                        "title": issue.title,
                        "status": issue.status,
                        "created_at": issue.created_at.isoformat() if issue.created_at else "",
                    },
                    topic=topic,
                    changes=changes,
                    sessions=by_issue.get(str(issue.id), []),
                    incidents=incidents,
                    branch=open_pull_in(changes, topic),
                )
            )
        )

    # 三次稳定排序,优先级从低到高:先按新旧,再让"等着的"按等得最久在前,
    # 最后分段。空串在第二趟里对跑着与落了的行不起作用,顺序原样保留。
    items.sort(key=lambda card: card.updated_at, reverse=True)
    items.sort(key=lambda card: card.waiting_since)
    items.sort(key=lambda card: ORDER.index(card.state) if card.state in ORDER else len(ORDER))

    counts = {"waiting": 0, "running": 0, "landed": 0}
    for card in items:
        counts[card.state] = counts.get(card.state, 0) + 1
    return IssueBoardDTO(items=items, counts=counts, total=len(items))

def continue_payload(
    *,
    issue: dict,
    repo: str,
    repo_id: Any,
    tenant: str,
    topic: str,
    instruction: str,
) -> dict:
    """一轮"继续改"在工作流眼里是什么样。

    它和人在 GitHub 上 @gwei 走的是同一条路:同一支 fix_suggestion_workflow、
    同一个话题、同一个 `_thread_for`。所以"分支沿用、PR 不新开"不是这里另写
    一套判断,而是那条路本来就这么做。

    标题与正文取议题自己的:一轮继续改是往这条线上再加一笔,不是重写这条议题。
    人说的话进 signal——事故记下它,时间线上"第几轮说了什么"就是从这儿来的。
    """
    return {
        "tenant_slug": tenant,
        "repo_full_name": repo,
        "repo_github_id": repo_id,
        "issue_github_id": issue["github_id"],
        "issue_number": issue["number"],
        "topic": topic,
        "title": issue["title"],
        "body": issue["body"],
        "source": "console",
        "signal": {
            "source": "console",
            "subject": topic,
            "title": instruction,
            "detail": instruction,
            "severity": "low",
            "ref": f"console-{uuid4().hex[:12]}",
        },
    }


@router.post("/api/issues/{issue_id}/continue")
async def continue_issue(
    issue_id: str,
    body: ContinueRoundDTO,
    request: Request,
    tenant: str | None = None,
) -> ContinuedDTO:
    """从界面发起新一轮:话题不变、分支不变、PR 不新开。

    权限借用 `changes.approve`:两件事是一类——此刻有人在场,允许平台再动一次手。
    真要细分的话是加一条新权限,不是在这里各自判断。
    """
    scope = tenant_scope(request, tenant)
    try:
        wanted = UUID(issue_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Issue not found") from None

    instruction = body.instruction.strip()
    if not instruction:
        raise HTTPException(status_code=422, detail="写一句要改什么再来")
    loaded = await _load_issue(wanted, scope)
    # 按议题所在的仓库判:只被授了 acme/api 的人,对 acme/web 的议题发起不动。
    require(request, "changes.approve", loaded["repo_slug"])
    topic = topic_of(loaded["repo"], loaded["issue"]["number"])
    payload = continue_payload(
        issue=loaded["issue"],
        repo=loaded["repo"],
        repo_id=loaded["repo_id"],
        tenant=loaded["tenant"],
        topic=topic,
        instruction=instruction,
    )
    queued = await enqueue_workflow(
        "gwei-fix", fix_suggestion_workflow, uuid4().hex, payload
    )
    logger.info(
        "Continue round queued for %s: %s", topic, queued.get("workflow_id")
    )
    return ContinuedDTO.model_validate(queued)
