# engine/api/routes/repos.py
"""仓库怎么进工作区、怎么出去 —— 人来接,不由投递自己长出来。

读侧只有一个上下文:接入之前先知道"这个工作区能接哪些来源"。来源清单由装着的
适配器答(`registry.webhook_adapters()`),核心里没有一张写死 github / cnb / gitlab
的表 —— 加一个新来源仍然是装一个插件的事。

写侧三条路径:

| 路径 | 做什么 | 幂等 |
| --- | --- | --- |
| `PUT /api/repos/{source}/{owner}/{name}` | 接入 | 是:同一个再接一次不改任何东西 |
| `DELETE /api/repos/{source}/{owner}/{name}` | 解除接入 | 是:本来没接就是 false |
| `PUT /api/repos/{source}/{owner}/{name}/project` | 挂到另一个项目 | 是 |
| `POST /api/repos/{source}/{owner}/{name}/issues` | 再读一次仓库已有的议题 | 是 |

接入那一刻会主动读一次这个仓库已有的议题(`sync_issues`):"这一道账从此刻起管
这份代码"如果只对以后的投递成立,人接完看到的是一张空板子,而出问题的那条议题
通常早在接之前就开了。这是**读**,不是替人跑一次:补进来的是议题事实,不产生评论、
不跑模型 —— 判据是接入答复里的 `issueSync.added`,不是"起了几个工作流"。

仓库全名在两段和两段以上(`/api/repos/gitlab/group/sub/repo`):GitLab 的子组也是
合法的所有者,按段数卡死会让它接不进来。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from engine.api.auth import by_of, require, workspace_access
from engine.api.schemas import RepoConnectDTO, RepoSourceDTO, RepoSyncDTO
from engine.auth import audit

router = APIRouter()
logger = logging.getLogger(__name__)


class ProjectRefDTO(BaseModel):
    """仓库挂到哪个项目。空串 = 挂回按全名第一段的默认归属。"""

    project: str = Field("", max_length=255)


async def _tenant(request: Request, writing: bool):
    """当前工作区的 (slug, id)。写操作要 `settings.write`:仓库是这一道账的边界。"""
    from engine.db import async_session_factory
    from engine.db.models import Tenant
    from engine.shared.config import config

    if writing:
        require(request, "settings.write")
    tenant = workspace_access(request) or config.settings.default_tenant_slug
    async with async_session_factory() as session:
        tenant_id = await session.scalar(select(Tenant.id).where(Tenant.slug == tenant))
    if tenant_id is None:
        raise HTTPException(status_code=404, detail=f"工作区不存在:{tenant}")
    return tenant, tenant_id


@router.get("/api/repos/sources")
async def list_sources(request: Request) -> list[RepoSourceDTO]:
    """这个部署能接哪些来源。装着的适配器说了算,不是一张写死的清单。"""
    from engine.projects.connect import known_sources

    require(request, "settings.read")
    return [RepoSourceDTO(source=name, label=_label(name)) for name in known_sources()]


def _label(source: str) -> str:
    """来源说给人听的名字。认不出来的就照原样念,不编一个。"""
    return {"github": "GitHub", "gitlab": "GitLab", "cnb": "CNB"}.get(source, source)


@router.put("/api/repos/{source}/{owner}/{name}")
async def connect_repo(
    source: str, owner: str, name: str, request: Request
) -> RepoConnectDTO:
    """接入一个仓库。

    接入的意思是"这一道账从现在起管这份代码",所以它当场读一次这个仓库已有的
    议题,把已经发生的事补进来 —— 否则人接完看到的是一张空板子,而出问题的那条
    议题通常早在接之前就开了。

    这一下是**读**:补进来的是议题事实,不拉代码、不跑模型、不回评。判据在答复
    里 —— `issue_sync.added` 是补进来的条数,不是"起了几个工作流"。
    """
    from engine.db import async_session_factory
    from engine.projects.connect import ConnectError, connect, known_sources, sync_issues

    tenant, tenant_id = await _tenant(request, writing=True)
    if source.lower() not in known_sources():
        raise HTTPException(
            status_code=422,
            detail=f"没有 {source} 的适配器:能接的来源是 {', '.join(known_sources()) or '无'}",
        )
    full_name = f"{owner}/{name}"
    source = source.lower()
    async with async_session_factory() as session:
        try:
            row, created = await connect(session, tenant_id, source, full_name)
            # 接进来之后立刻读一次已经发生的事:接之前就在的议题如果不补,板子上
            # 就只剩"接之后才开的"那些,人分不清是没议题还是没读到。
            synced = await sync_issues(session, tenant_id, row, source, full_name)
            await session.commit()
        except ConnectError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    await audit.record(
        "repo.connect",
        identity=by_of(request, ""),
        target=f"{source}/{full_name}",
        detail={"created": created, "tenant": tenant, **synced},
        ip=request.client.host if request.client else "",
    )
    return RepoConnectDTO(
        slug=row.slug,
        source=row.source,
        name=row.name,
        created=created,
        issue_sync=RepoSyncDTO(**synced),
    )


@router.post("/api/repos/{source}/{owner}/{name}/issues")
async def pull_repo_issues(source: str, owner: str, name: str, request: Request) -> RepoSyncDTO:
    """再读一次这个仓库已有的议题。

    接入那一刻已经读过一次;这条路径是给人补的 —— 读的时候上游正好不通、或者
    接入之后仓库上又开了几十条。它与接入时读的是同一个函数,不会读成两份。
    """
    from engine.db import async_session_factory
    from engine.projects.connect import pull_issues

    tenant, tenant_id = await _tenant(request, writing=True)
    async with async_session_factory() as session:
        result = await pull_issues(session, tenant_id, source.lower(), f"{owner}/{name}")
        await session.commit()
    await audit.record(
        "repo.issues.pull",
        identity=by_of(request, ""),
        target=f"{source}/{owner}/{name}",
        detail={"tenant": tenant, **result},
        ip=request.client.host if request.client else "",
    )
    return RepoSyncDTO(**result)


@router.delete("/api/repos/{source}/{owner}/{name}")
async def disconnect_repo(source: str, owner: str, name: str, request: Request) -> dict:
    """解除接入。议题与账本行留着:账是发生过的事,不跟着绑定一起消失。"""
    from engine.db import async_session_factory
    from engine.projects.connect import ConnectError, disconnect

    tenant, tenant_id = await _tenant(request, writing=True)
    async with async_session_factory() as session:
        try:
            removed = await disconnect(session, tenant_id, source, f"{owner}/{name}")
            await session.commit()
        except ConnectError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    await audit.record(
        "repo.disconnect",
        identity=by_of(request, ""),
        target=f"{source}/{owner}/{name}",
        detail={"removed": removed, "tenant": tenant},
        ip=request.client.host if request.client else "",
    )
    return {"removed": removed}


@router.put("/api/repos/{source}/{owner}/{name}/project")
async def attach_repo(
    source: str, owner: str, name: str, body: ProjectRefDTO, request: Request
) -> dict:
    """把已接入的仓库挂到另一个项目。空串 = 回到按全名第一段的默认归属。"""
    from engine.db import async_session_factory
    from engine.projects.connect import ConnectError, attach
    from engine.projects.settings import reload_project_snapshot

    tenant, tenant_id = await _tenant(request, writing=True)
    async with async_session_factory() as session:
        try:
            row = await attach(session, tenant_id, source, f"{owner}/{name}", body.project)
            await session.commit()
        except ConnectError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        parent_id = row.parent_id
        project = None
        if parent_id is not None:
            from engine.db.models import Project

            parent = await session.get(Project, parent_id)
            project = parent.slug if parent is not None else None
    # 发布解析读的是内存快照里的"仓库属于哪个项目",改完就刷一次
    await reload_project_snapshot()
    await audit.record(
        "repo.attach",
        identity=by_of(request, ""),
        target=f"{source}/{owner}/{name}",
        detail={"project": project, "tenant": tenant},
        ip=request.client.host if request.client else "",
    )
    return {"project": project}
