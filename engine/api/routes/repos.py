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

仓库全名在两段和两段以上(`/api/repos/gitlab/group/sub/repo`):GitLab 的子组也是
合法的所有者,按段数卡死会让它接不进来。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from engine.api.auth import by_of, require, workspace_access
from engine.api.schemas import RepoConnectDTO, RepoSourceDTO
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

    接入只是"这一道账开始管这份代码":投递从这一步起才会被处理。它**不拉代码、
    不建议题、不跑工作流** —— 第一次投递才是那件事。
    """
    from engine.db import async_session_factory
    from engine.projects.connect import ConnectError, connect, known_sources

    tenant, tenant_id = await _tenant(request, writing=True)
    if source.lower() not in known_sources():
        raise HTTPException(
            status_code=422,
            detail=f"没有 {source} 的适配器:能接的来源是 {', '.join(known_sources()) or '无'}",
        )
    full_name = f"{owner}/{name}"
    async with async_session_factory() as session:
        try:
            row, created = await connect(session, tenant_id, source, full_name)
            await session.commit()
        except ConnectError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    await audit.record(
        "repo.connect",
        identity=by_of(request, ""),
        target=f"{source}/{full_name}",
        detail={"created": created, "tenant": tenant},
        ip=request.client.host if request.client else "",
    )
    return RepoConnectDTO(
        slug=row.slug, source=row.source, name=row.name, created=created
    )


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
