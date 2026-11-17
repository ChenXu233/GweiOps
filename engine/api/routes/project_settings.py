"""项目这一级的读写口 —— 可见性、默认发布参数、项目级凭据。

为什么要这一层:`plugin_settings` 的键是 (租户, scope, key),它只回答"整个
工作区怎么配"。项目之间不一样的地方原来只能靠"每个仓库行抄一遍"表达,同一个
项目的三个仓库抄三份,改一次要改三处 —— 而那些副本迟早有一份没跟上。

三样东西一个形状,读法各自说清:

- **可见性**:`workspace` 谁都是成员就看得见;`restricted` 的项目连同它下面的
  仓库不列给不是这个工作区成员的人。这不替代 `require` —— 它只管"列不列出来",
  不管"能不能动"
- **默认发布参数**:项目这一层在发布解析里位于工作区默认与仓库行之间,项目下
  每个仓库(含以后新增的)都先读它
- **项目级凭据**:值进密钥仓库(`scope=project:<slug>`),库里这一行只记键与
  说明。响应里永不回显明文,只回答"设了没有"
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from engine.api.auth import by_of, identity_of, require, workspace_access
from engine.auth import audit
from engine.projects import CREDENTIAL_SCOPE_PREFIX, VISIBILITIES
from engine.projects.settings import settings_of_project
from engine.shared.config import config
from engine.shared.settings_store import create_settings_store

router = APIRouter()
logger = logging.getLogger(__name__)


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


async def _project_or_404(slug: str, request: Request):
    from engine.db import async_session_factory
    from engine.db.models import Project, Tenant

    tenant = workspace_access(request) or config.settings.default_tenant_slug
    async with async_session_factory() as session:
        tenant_id = await session.scalar(select(Tenant.id).where(Tenant.slug == tenant))
        if tenant_id is None:
            raise HTTPException(status_code=404, detail=f"工作区不存在:{tenant}")
        project = await session.scalar(
            select(Project).where(
                Project.tenant_id == tenant_id,
                Project.slug == slug,
                Project.parent_id.is_(None),
            )
        )
        if project is None:
            raise HTTPException(status_code=404, detail=f"没有这个项目:{slug}")
        return tenant, tenant_id, project


class ProjectSettingsDTO(BaseModel):
    visibility: str | None = None
    defaults: dict[str, str] | None = None


class CredentialDTO(BaseModel):
    """一条项目级凭据。`value` 只写不读 —— 读回来的响应里没有这一栏。"""

    key: str = Field(..., min_length=1, max_length=63)
    value: str = Field("", max_length=8192)
    description: str = Field("", max_length=255)


async def _load(slug: str, request: Request) -> dict:
    """这个项目当前的样子。凭据只回答"设了没有",值从不回显。"""
    from engine.db import async_session_factory
    from engine.db.models import Project, ProjectSetting

    tenant, _tenant_id, project = await _project_or_404(slug, request)
    async with async_session_factory() as session:
        row = await session.scalar(
            select(ProjectSetting).where(ProjectSetting.project_id == project.id)
        )
        payload = settings_of_project(project, row).dto()
        payload["repos"] = [
            child.slug
            for child in (
                await session.execute(select(Project).where(Project.parent_id == project.id))
            ).scalars()
        ]
    # "设了没有"以密钥仓库为准:行里的键清单只是索引,值不在库里
    live = config.stored(f"{CREDENTIAL_SCOPE_PREFIX}{slug}", tenant)
    payload["credentials"] = [
        {**item, "set": bool(live.get(str(item["key"])))}
        for item in payload["credentials"]
    ]
    payload["workspace"] = tenant
    return payload


@router.get("/api/projects/{slug}/settings")
async def get_project_settings(slug: str, request: Request) -> dict:
    require(request, "settings.read")
    return {"project": await _load(slug, request)}


@router.put("/api/projects/{slug}/settings")
async def put_project_settings(slug: str, body: ProjectSettingsDTO, request: Request) -> dict:
    """可见性与默认发布参数。两者都在这一行里,整份写、不担心字段级 diff。"""
    require(request, "settings.write")
    if body.visibility is not None and body.visibility not in VISIBILITIES:
        raise HTTPException(
            status_code=422, detail=f"visibility 只能是 {' / '.join(VISIBILITIES)}"
        )
    from engine.api.routes.release_settings import _validate_values
    from engine.db import async_session_factory
    from engine.db.models import ProjectSetting

    if body.defaults is not None:
        errors = _validate_values(body.defaults)
        if errors:
            raise HTTPException(status_code=422, detail="；".join(errors))

    tenant, tenant_id, project = await _project_or_404(slug, request)
    async with async_session_factory() as session:
        row = await session.scalar(
            select(ProjectSetting).where(ProjectSetting.project_id == project.id)
        )
        if row is None:
            row = ProjectSetting(tenant_id=tenant_id, project_id=project.id, credentials=[])
            session.add(row)
        if body.visibility is not None:
            row.visibility = body.visibility
        if body.defaults is not None:
            row.defaults = {str(k): str(v) for k, v in body.defaults.items()}
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()

    from engine.projects import reload_project_snapshot

    await reload_project_snapshot()
    await audit.record(
        "project.settings",
        identity=identity_of(request),
        target=f"project:{slug}",
        detail={"visibility": body.visibility, "keys": sorted(body.defaults or {})},
        ip=_ip(request),
    )
    return {"project": await _load(slug, request)}


@router.put("/api/projects/{slug}/credentials/{key}")
async def put_project_credential(
    slug: str, key: str, body: CredentialDTO, request: Request
) -> dict:
    """写一条项目级凭据。值进密钥仓库,库里只留键与说明。

    空值等于删掉:凭据没有"空着"这种状态 —— 空着和没设是同一件事,分成两种会让
    "设了没有"永远有两种答案。
    """
    require(request, "settings.write")
    if key != body.key:
        raise HTTPException(status_code=400, detail="路径里的键与正文里的键不一致")

    tenant, tenant_id, project = await _project_or_404(slug, request)
    from engine.db import async_session_factory
    from engine.db.models import ProjectSetting

    scope = f"{CREDENTIAL_SCOPE_PREFIX}{slug}"
    store = create_settings_store()
    if not body.value:
        await store.delete(scope, key, tenant=tenant)
    else:
        await store.put(scope, {key: body.value}, by=by_of(request, ""), tenant=tenant)

    async with async_session_factory() as session:
        row = await session.scalar(
            select(ProjectSetting).where(ProjectSetting.project_id == project.id)
        )
        if row is None:
            row = ProjectSetting(tenant_id=tenant_id, project_id=project.id, credentials=[])
            session.add(row)
        items = [dict(item) for item in (row.credentials or [])]
        items = [item for item in items if str(item.get("key")) != key]
        if body.value:
            items.append(
                {
                    "key": key,
                    "description": body.description,
                    "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
            )
        row.credentials = items
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()

    await audit.record(
        "project.credential",
        identity=identity_of(request),
        target=f"project:{slug}/{key}",
        detail={"set": bool(body.value)},
        ip=_ip(request),
    )
    return {"project": await _load(slug, request)}


__all__ = ["router"]
