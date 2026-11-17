# engine/projects/settings.py
"""项目级的值从哪来、谁会读到。

三样东西共用一行 `project_settings`,但读法各不相同:

| 值 | 存在哪 | 谁读 |
| --- | --- | --- |
| `visibility` | 库里那一行 | 控制台的仓库与项目列表 |
| 默认发布参数 | 库里那一行的 `defaults` | `release.resolve_release_config` |
| 项目级凭据 | 值在密钥仓库(`scope=project:<slug>`),键清单在行里 | 配置页;插件按 scope 读 |

凭据的值不进这张表:表在业务库里,谁读到库就都读到了。键清单留在行里,是因为
"这个项目有几条凭据、谁什么时候换的"要看得见,而明文不需要出现在同一个地方。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.db.models import Project, ProjectSetting

# 项目级凭据在密钥仓库里的 scope 名
CREDENTIAL_SCOPE_PREFIX = "project:"

VISIBILITIES = ("workspace", "restricted")


@dataclass(frozen=True)
class ProjectSettings:
    """一个项目当前生效的值。没有那一行时就是这里的默认:全用工作区默认。"""

    project_id: str = ""
    slug: str = ""
    visibility: str = "workspace"
    defaults: dict[str, str] = field(default_factory=dict)
    credentials: tuple[dict, ...] = ()

    @property
    def restricted(self) -> bool:
        return self.visibility == "restricted"

    def dto(self) -> dict:
        return {
            "project_id": self.project_id,
            "slug": self.slug,
            "visibility": self.visibility,
            "defaults": dict(self.defaults),
            "credentials": [
                {
                    "key": str(item.get("key", "")),
                    "description": str(item.get("description", "")),
                    "updated_at": str(item.get("updated_at", "")),
                }
                for item in self.credentials
            ],
        }


def settings_of_project(project: Project, row: ProjectSetting | None) -> ProjectSettings:
    """一行 `projects` + 它可能有的那一行 `project_settings` → 生效值。"""
    if row is None:
        return ProjectSettings(project_id=str(project.id), slug=project.slug)
    return ProjectSettings(
        project_id=str(project.id),
        slug=project.slug,
        visibility=str(row.visibility or "workspace"),
        defaults={str(k): str(v) for k, v in (row.defaults or {}).items()},
        credentials=tuple(row.credentials or ()),
    )


async def project_settings(
    session: AsyncSession, tenant_id: uuid.UUID, slugs: list[str]
) -> dict[str, ProjectSettings]:
    """按 slug 批量取项目级的值。范围闸与列表都用它,不按行各查一次。

    项目这个 slug 只在项目行上(`parent_id` 空);仓库行同名字段是它自己的
    slug,两者共用名字空间,所以这里按 `parent_id IS NULL` 找。
    """
    wanted = [slug for slug in dict.fromkeys(slugs) if slug]
    if not wanted:
        return {}
    projects = (
        await session.execute(
            select(Project).where(
                Project.tenant_id == tenant_id,
                Project.slug.in_(wanted),
                Project.parent_id.is_(None),
            )
        )
    ).scalars().all()
    if not projects:
        return {}
    rows = {
        row.project_id: row
        for row in (
            await session.execute(
                select(ProjectSetting).where(
                    ProjectSetting.project_id.in_([p.id for p in projects])
                )
            )
        ).scalars()
    }
    return {
        project.slug: settings_of_project(project, rows.get(project.id))
        for project in projects
    }


async def project_of_repo(
    session: AsyncSession, tenant_id: uuid.UUID, repo_slug: str
) -> tuple[Project | None, Project | None]:
    """一个仓库行,以及它所属的项目行。仓库没挂项目时第二项是 None。"""
    repo = await session.scalar(
        select(Project).where(Project.tenant_id == tenant_id, Project.slug == repo_slug)
    )
    if repo is None or repo.parent_id is None:
        return repo, None
    parent = await session.get(Project, repo.parent_id)
    return repo, parent


__all__ = [
    "CREDENTIAL_SCOPE_PREFIX",
    "VISIBILITIES",
    "ProjectSettings",
    "project_of_repo",
    "project_settings",
    "settings_of_project",
]


async def reload_project_snapshot() -> None:
    """把项目级的值与"仓库属于哪个项目"读一次,装进 `config` 的快照。

    发布解析是同步的(工作流步骤里到处在调),读不了库 —— 它读的是这份快照。
    写入接口与启动流程各调一次;调用之后这一瞬间的快照就是库里的样子。
    """
    from engine.db import async_session_factory
    from engine.db.models import Project, Tenant
    from engine.shared.config import config

    async with async_session_factory() as session:
        tenants = {
            row.id: row.slug
            for row in (await session.execute(select(Tenant))).scalars()
        }
        defaults: dict[str, dict[str, dict[str, str]]] = {}
        for row, project_slug in (
            await session.execute(
                select(ProjectSetting, Project.slug).join(
                    Project, Project.id == ProjectSetting.project_id
                )
            )
        ).all():
            slug = tenants.get(row.tenant_id)
            if slug:
                defaults.setdefault(slug, {})[project_slug] = {
                    str(k): str(v) for k, v in (row.defaults or {}).items()
                }
        repo_project: dict[str, dict[str, str]] = {}
        parent_slugs = {
            project.id: project.slug
            for project in (
                await session.execute(select(Project).where(Project.parent_id.is_(None)))
            ).scalars()
        }
        for project in (
            await session.execute(select(Project).where(Project.parent_id.is_not(None)))
        ).scalars():
            slug = tenants.get(project.tenant_id)
            parent = parent_slugs.get(project.parent_id)
            if slug and parent:
                repo_project.setdefault(slug, {})[project.slug] = parent
    config.apply_projects(defaults=defaults, repo_project=repo_project)
