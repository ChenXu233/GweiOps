# engine/api/routes/console.py
"""控制台的只读小件 —— 工作区、仓库列表与团队设置。

议题与变更各有自己的接口([issues.py](issues.py)、[changes.py](changes.py)),
这里只留三个没有别处可去的读取点。

原来的 `/api/dashboard*`、`/api/runs`、`/api/issues` 已经删掉:控制室与执行记录
两个页面不在了,聚合数的去处是议题板与议题详情。留着只有一个消费者、而那个消费者
已经不存在的接口,只会让"平台到底有哪些数据"越来越难答。
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from engine.api.schemas import (
    ProjectDTO,
    ProjectListDTO,
    RepoDTO,
    SettingsDTO,
    WorkspaceDTO,
    WorkspaceListDTO,
)
from engine.api.auth import identity_of, workspace_access
from engine.db import async_session_factory
from engine.db.models import Issue, Membership, Project, Tenant
from engine.shared.config import config


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


@router.get("/api/workspaces")
async def list_workspaces(request: Request) -> WorkspaceListDTO:
    """我可以进的工作区(租户),以及每个里面有几个仓库、来自哪些平台。

    人这一侧问的是"我属于哪几家" —— 这个选择器换的是数据边界,列出一个我进不去
    的工作区,只会给出"它在这儿但你不能点"的坏体验。机器那一侧(静态令牌 / 密钥)
    本来就写死一个租户,回答的还是那一个。
    """
    scope = workspace_access(request)
    identity = identity_of(request)
    async with async_session_factory() as session:
        stmt = select(Tenant).order_by(Tenant.created_at)
        if scope:
            stmt = stmt.where(Tenant.slug == scope)
        elif identity is not None and identity.person_id:
            stmt = stmt.join(Membership, Membership.tenant_id == Tenant.id).where(
                Membership.person_id == uuid.UUID(identity.person_id),
                Membership.status != "disabled",
            )
        tenants = (await session.execute(stmt)).scalars().all()

        counts: dict[str, int] = {}
        sources: dict[str, set[str]] = {}
        if tenants:
            rows = (
                await session.execute(
                    select(Project.tenant_id, Project.source, func.count(Project.id))
                    .group_by(Project.tenant_id, Project.source)
                )
            ).all()
            for tenant_id, source, count in rows:
                key = str(tenant_id)
                counts[key] = counts.get(key, 0) + int(count)
                sources.setdefault(key, set()).add(str(source or ""))

    return WorkspaceListDTO(
        items=[
            WorkspaceDTO(
                slug=t.slug,
                name=t.name,
                repos=counts.get(str(t.id), 0),
                sources=sorted(s for s in sources.get(str(t.id), set()) if s),
            )
            for t in tenants
        ],
        current=scope or (tenants[0].slug if tenants else ""),
    )


@router.get("/api/repos")
async def list_repos(request: Request) -> list[RepoDTO]:
    """这个工作区里的仓库。工作区从路径来(`/api/workspaces/acme/repos`),不是参数。

    同一个仓库名在两个工作区里是两份数据,所以每行都带上来源;仓库上面还有项目,
    所以每行也带上项目 —— 范围闸的三档(工作区 / 项目 / 仓库)就是按这两栏算的。
    """
    scope = workspace_access(request)
    async with async_session_factory() as session:
        stmt = (
            select(
                Project,
                func.count(Issue.id).label("issue_count"),
                func.max(Issue.created_at).label("last_activity"),
            )
            .outerjoin(Issue, Issue.project_id == Project.id)
            .where(Project.parent_id.is_not(None))
            .group_by(Project.id)
            .order_by(Project.created_at)
        )
        if scope:
            stmt = stmt.join(Tenant, Project.tenant_id == Tenant.id).where(Tenant.slug == scope)
        rows = (await session.execute(stmt)).all()
        parents = await _project_names(session, [project.parent_id for project, _, _ in rows])

    return [
        RepoDTO(
            id=str(project.id),
            name=project.name,
            icon="📦",
            status="running",
            issueCount=issue_count,
            activeAgents=0,
            lastSyncAt=(last_activity or project.created_at).isoformat(),
            source=project.source or "github",
            slug=project.slug,
            project=(parents.get(project.parent_id) or ("", ""))[0],
            projectName=(parents.get(project.parent_id) or ("", ""))[1],
        )
        for project, issue_count, last_activity in rows
    ]


async def _project_names(session, ids) -> dict:
    """父行的 (slug, name)。一次取回:一页仓库不该按行各查一次父。"""
    wanted = [i for i in {pid for pid in ids if pid is not None}]
    if not wanted:
        return {}
    rows = (
        await session.execute(
            select(Project.id, Project.slug, Project.name).where(Project.id.in_(wanted))
        )
    ).all()
    return {row[0]: (row[1], row[2]) for row in rows}


@router.get("/api/projects")
async def list_projects(request: Request) -> ProjectListDTO:
    """这个工作区里的项目,以及每个项目下面有几个仓库、几条议题。

    项目是仓库上面那一级,也是范围闸上的中间那一档:整个工作区 → 某个项目 →
    某个仓库。它是资源不只是标签 —— 项目级的可见性、默认动作、凭据要有地方摆。
    工作区从路径来,不从查询串来。
    """
    scope = workspace_access(request)
    async with async_session_factory() as session:
        stmt = select(Project).where(Project.parent_id.is_(None)).order_by(Project.created_at)
        if scope:
            stmt = stmt.join(Tenant, Project.tenant_id == Tenant.id).where(Tenant.slug == scope)
        parents = (await session.execute(stmt)).scalars().all()
        if not parents:
            return ProjectListDTO(items=[])

        children = (
            await session.execute(
                select(Project.parent_id, Project.id).where(
                    Project.parent_id.in_([p.id for p in parents])
                )
            )
        ).all()
        repos_of: dict = {}
        for parent_id, _ in children:
            repos_of[parent_id] = repos_of.get(parent_id, 0) + 1
        # 子仓的议题数一次取回再按父汇总:项目一多,逐个查就成了 N 次。
        child_to_parent = {child_id: parent_id for parent_id, child_id in children}
        child_ids = list(child_to_parent)
        issues_of: dict = {}
        if child_ids:
            for project_id, count in (
                await session.execute(
                    select(Issue.project_id, func.count(Issue.id))
                    .where(Issue.project_id.in_(child_ids))
                    .group_by(Issue.project_id)
                )
            ).all():
                issues_of[project_id] = int(count)

    # 一个项目有几条议题,问的是它下面所有仓库的合计。
    by_parent: dict = {}
    for child_id, count in issues_of.items():
        parent_id = child_to_parent.get(child_id)
        if parent_id is not None:
            by_parent[parent_id] = by_parent.get(parent_id, 0) + count

    return ProjectListDTO(
        items=[
            ProjectDTO(
                id=str(p.id),
                slug=p.slug,
                name=p.name,
                repos=repos_of.get(p.id, 0),
                issues=by_parent.get(p.id, 0),
            )
            for p in parents
        ]
    )


@router.get("/api/settings")
async def team_settings(request: Request) -> SettingsDTO:
    """团队设置。配额与注册那两块的现状从真实配置算出来,不是写死的字符串。"""
    from engine.quota import QuotaError, limits_for

    tenant = workspace_access(request) or ""
    try:
        issues = limits_for(tenant).get("issues")
    except QuotaError:
        issues = None
    return SettingsDTO(
        teamName="Self-hosted",
        memberCount=1,
        adminCount=1,
        plan="selfhost",
        planPrice="-",
        # 没声明限量才是"不限";写错的值在上面的 except 里按不限展示,设置页会报错
        issueQuota=(
            "不限" if issues is None or not issues.window_hours
            else f"{issues.amount} / {issues.window_hours}h"
        ),
        notificationChannels=[],
        ssoProvider="OIDC" if config.settings.oidc_issuer else "—",
    )
