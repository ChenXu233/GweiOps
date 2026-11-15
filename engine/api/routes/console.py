# engine/api/routes/console.py
"""控制台的只读小件 —— 仓库列表与团队设置。

议题与变更各有自己的接口([issues.py](issues.py)、[changes.py](changes.py)),
这里只留两个没有别处可去的读取点。

原来的 `/api/dashboard*`、`/api/runs`、`/api/issues` 已经删掉:控制室与执行记录
两个页面不在了,聚合数的去处是议题板与议题详情。留着只有一个消费者、而那个消费者
已经不存在的接口,只会让"平台到底有哪些数据"越来越难答。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from engine.api.schemas import RepoDTO, SettingsDTO
from engine.db import async_session_factory
from engine.db.models import Issue, Project


def _any_read(request: Request) -> None:
    """控制台的读权限:有任意一个读权限就能看。"""
    from engine.api.auth import actor_of, auth_required

    if not auth_required():
        return
    actor = actor_of(request)
    if actor is None:
        raise HTTPException(status_code=401, detail="未登录或令牌无效")
    if actor.permissions and not (
        {"changes.read", "settings.read", "plugins.read"} & set(actor.permissions)
    ):
        raise HTTPException(status_code=403, detail="缺少读权限")


router = APIRouter(dependencies=[Depends(_any_read)])
logger = logging.getLogger(__name__)


@router.get("/api/repos")
async def list_repos() -> list[RepoDTO]:
    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(
                    Project,
                    func.count(Issue.id).label("issue_count"),
                    func.max(Issue.created_at).label("last_activity"),
                )
                .outerjoin(Issue, Issue.project_id == Project.id)
                .group_by(Project.id)
                .order_by(Project.created_at)
            )
        ).all()
    return [
        RepoDTO(
            id=str(project.id),
            name=project.name,
            icon="📦",
            status="running",
            issueCount=issue_count,
            activeAgents=0,
            lastSyncAt=(last_activity or project.created_at).isoformat(),
        )
        for project, issue_count, last_activity in rows
    ]


@router.get("/api/settings")
async def team_settings() -> SettingsDTO:
    # selfhost 单租户默认值;多租户/订阅接入后由计费插件提供
    return SettingsDTO(
        teamName="Self-hosted",
        memberCount=1,
        adminCount=1,
        plan="selfhost",
        planPrice="-",
        issueQuota="无限",
        notificationChannels=[],
        ssoProvider="—",
    )
