# engine/projects/connect.py
"""仓库怎么进工作区 —— 人来接,不是投递自己长出来。

一次投递只说得清"哪份代码上发生了一件事",说不清"这道账要不要管它"。所以
仓库的建立是**显式**的:

1. 人接仓库(`PUT /api/repos/{source}/{owner}/{name}`),或者在告警/信号页
   把某个地址认领进来(见 `adopt`);
2. 投递到达时只认已接入的仓库,未接入的来源一律不落库、不开工作流。

这条边界的判据是"这个工作区里有没有这一行",不是一个过滤器:接到没接入的
仓库时,工作流连启动的机会都不该有 —— 否则一次公网可达的 webhook 就能让引擎
替陌生人拉代码、跑模型。

接入本身只写一行,幂等:重复接同一个仓库不改任何东西。项目按仓库全名第一段
归位(与投递时的默认归属同一个规则,见 `engine/workflows/pipeline.py`),要搬到
别的项目改 `parent_id`。
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 仓库全名:所有者/名字,两段都不能为空。GitLab 的子组也是合法的所有者
# (`group/sub/repo`),所以这里不限制段数,只要求每段是常见字符。
_FULL_NAME = re.compile(r"^[A-Za-z0-9_.\-]+(/[A-Za-z0-9_.\-]+)+$")
# 每段都得有内容:`acme/` 与 `acme//api` 不是仓库全名,是写错了。
_SLUG_PART = re.compile(r"[^A-Za-z0-9_.\-]+")


class ConnectError(ValueError):
    """接不进来的原因。调用方把它翻成 4xx,不说"出错了"。"""


def repo_slug(source: str, full_name: str) -> str:
    """仓库在这棵树上的 slug:`来源-仓库全名`,`/` 也压成 `-`。

    分隔符只有一个是因为它要进 URL(slug 不可逆,要来源和全名读
    `source` / `name` 两栏)。
    """
    name = (full_name or "").replace("/", "-")
    return f"{source}-{name}" if source else name


def project_slug_of(full_name: str) -> str:
    """仓库全名所属的项目:取第一段。`acme/api` 属于项目 `acme`。

    GitLab 那种 `group/sub/repo` 取的是 `group`:项目是"这家是谁",不是路径层级。
    """
    head, _, _ = (full_name or "").partition("/")
    return _SLUG_PART.sub("-", head).strip("-")


def normalize(source: str, full_name: str) -> tuple[str, str]:
    """(来源, 全名) 归一化。写不清就在这里拒,不留到落库时才炸。"""
    source = (source or "").strip().lower()
    full_name = (full_name or "").strip().strip("/")
    if not source:
        raise ConnectError("没有来源:仓库属于哪个平台,得说清楚")
    if not _FULL_NAME.match(full_name):
        raise ConnectError(f"仓库全名要写成 `所有者/名字`:{full_name!r}")
    return source, full_name


def known_sources() -> list[str]:
    """能接的来源 —— 由装着的适配器说,不由核心写死一张表。"""
    from engine.plugin_manager import registry

    try:
        instances = registry.webhook_adapters()
    except Exception:  # noqa: BLE001 - 注册表没起来 = 一个来源都没有,不是这里该炸的错
        logger.info("插件注册表没起来,当前没有可接入的来源")
        return []
    return sorted({str(getattr(item, "source", "") or "") for item in instances} - {""})


async def connect(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    source: str,
    full_name: str,
    *,
    project: str = "",
) -> tuple[object, bool]:
    """接一个仓库,返回 (那一行, 是不是新建的)。

    幂等:同一个 (来源, 全名) 再接一次,返回原来那行,什么都不改。要改项目,
    调 `attach`(那是另一个决定)。
    """
    from engine.db.models import Project

    source, full_name = normalize(source, full_name)
    slug = repo_slug(source, full_name)
    found = await session.scalar(
        select(Project).where(Project.tenant_id == tenant_id, Project.slug == slug)
    )
    if found is not None:
        return found, False

    if not project.strip():
        parent = await _project_row(session, tenant_id, project_slug_of(full_name))
    else:
        parent = await _project_row(session, tenant_id, _SLUG_PART.sub("-", project.strip()))
    row = Project(
        tenant_id=tenant_id,
        parent_id=parent.id if parent is not None else None,
        slug=slug,
        source=source,
        name=full_name,
    )
    session.add(row)
    await session.flush()
    logger.info("接入仓库 %s(%s → %s)", full_name, source, slug)
    return row, True


async def _project_row(session: AsyncSession, tenant_id: uuid.UUID, slug: str):
    """项目那一行:有就用,没有就建。`slug` 空 = 这个仓库不属于任何项目。"""
    from engine.db.models import Project

    if not slug:
        return None
    found = await session.scalar(
        select(Project).where(
            Project.tenant_id == tenant_id,
            Project.slug == slug,
            Project.parent_id.is_(None),
        )
    )
    if found is not None:
        return found
    created = Project(tenant_id=tenant_id, parent_id=None, slug=slug, source="", name=slug)
    session.add(created)
    await session.flush()
    return created


async def resolve(session: AsyncSession, tenant_id: uuid.UUID, source: str, full_name: str):
    """这个仓库接入过吗。没有就是 None —— 调用方据此如实报告"没接入"。"""
    from engine.db.models import Project

    source, full_name = normalize(source, full_name)
    return await session.scalar(
        select(Project).where(
            Project.tenant_id == tenant_id,
            Project.slug == repo_slug(source, full_name),
        )
    )


async def attach(session: AsyncSession, tenant_id: uuid.UUID, source: str, full_name: str,
                 project: str) -> object:
    """把一个已接入的仓库挂到另一个项目。空项目 = 挂回默认归属。"""
    row = await resolve(session, tenant_id, source, full_name)
    if row is None:
        raise ConnectError(f"这个工作区还没接入 {source} 的 {full_name}")
    slug = _SLUG_PART.sub("-", project.strip()) if project.strip() else project_slug_of(full_name)
    parent = await _project_row(session, tenant_id, slug)
    row.parent_id = parent.id if parent is not None else None
    await session.flush()
    return row


async def disconnect(session: AsyncSession, tenant_id: uuid.UUID, source: str, full_name: str) -> bool:
    """解除接入。议题与账本行都留着:账是发生过的事,不跟着绑定一起消失。

    只把仓库这一行删掉,投递就不再认它 —— 这是"不再管它",不是"忘了它"。
    """
    from engine.db.models import Project

    row = await resolve(session, tenant_id, source, full_name)
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


__all__ = [
    "ConnectError",
    "attach",
    "connect",
    "disconnect",
    "known_sources",
    "normalize",
    "project_slug_of",
    "repo_slug",
    "resolve",
]
