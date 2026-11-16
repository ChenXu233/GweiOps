# engine/plugin_manager/tenancy.py
"""租户级插件启停 —— SaaS 上"这个租户装不装它"存在哪、怎么读。

决定只有两种,按 `(租户, 插件)` 存:开、关。没存过就是"没选",落在平台的
默认上(平台提供的插件,租户默认启用)。

为什么不复用 `plugin_settings` 那套 scope 的打底/覆盖语义:`plugin_settings` 是
**配置**,打底是"继承公共值";这里是**授权**,语义是"默认拒绝/默认跟随平台"。
两者混在一起的后果是:人以为在改配置,实际在改授权,而配置可以继承,授权不该。

所以另起一张表 `plugin_tenancy`,主键 `(tenant, plugin)`,带 `enabled`、
`config`、`updated_by`、`updated_at`——第三方插件进 SaaS 之后,审计一定会问
"这个租户为什么能跑这个插件",那时要答得出是谁在什么时候打开的。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

TABLE = "plugin_tenancy"


@dataclass(frozen=True)
class TenancyRow:
    tenant: str
    plugin: str
    enabled: bool
    updated_by: str = ""
    updated_at: str = ""


class TenancyUnavailable(RuntimeError):
    """读不到租户决定。调用方按"平台默认"处理,并如实说这一次不知道。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _file_path() -> Any:
    from pathlib import Path

    from engine.shared.config import config

    ledger = Path(config.settings.change_ledger_path)
    return ledger.with_name("plugin_tenancy.json")


def _uses_file_backend() -> bool:
    from engine.shared.config import config

    return config.settings.change_ledger_backend == "file"


async def ensure_schema() -> None:
    """建表(checkfirst)。和账本、事故一样,启动时兜一次。"""
    if _uses_file_backend():
        return
    from engine.db.engine import engine
    from engine.db.models.plugin_tenancy import PluginTenancy

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: PluginTenancy.__table__.create(c, checkfirst=True))


async def load_tenancy(tenant: str = "") -> dict[str, bool]:
    """该租户的显式决定;没存过的插件不出现在结果里(不是 false)。

    "没存过"与"明确关掉"必须分得开:前者跟随平台默认,后者是租户的选择。
    把两者压成 false,页面上就再也开不回去了。
    """
    if _uses_file_backend():
        return _load_file(tenant)
    try:
        return await _load_db(tenant)
    except Exception:  # noqa: BLE001 - 库没起来时按"没有租户决定"处理
        logger.warning("读不到租户级的插件启停决定,这次按平台默认", exc_info=True)
        return {}


async def _load_db(tenant: str) -> dict[str, bool]:
    from sqlalchemy import select

    from engine.db.engine import async_session_factory
    from engine.db.models.plugin_tenancy import PluginTenancy

    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(PluginTenancy).where(PluginTenancy.tenant == (tenant or ""))
            )
        ).scalars().all()
    return {row.plugin: bool(row.enabled) for row in rows}


def _load_file(tenant: str) -> dict[str, bool]:
    import json

    path = _file_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    bucket = data.get(tenant or "") or {}
    return {name: bool(value) for name, value in bucket.items()}


async def rows(tenant: str = "") -> list[TenancyRow]:
    """该租户全部显式决定,带改的人和改的时间。控制台与审计用。"""
    if _uses_file_backend():
        return [
            TenancyRow(tenant=tenant or "", plugin=name, enabled=value)
            for name, value in _load_file(tenant).items()
        ]
    from sqlalchemy import select

    from engine.db.engine import async_session_factory
    from engine.db.models.plugin_tenancy import PluginTenancy

    async with async_session_factory() as session:
        found = (
            await session.execute(
                select(PluginTenancy).where(PluginTenancy.tenant == (tenant or ""))
            )
        ).scalars().all()
    return [
        TenancyRow(
            tenant=row.tenant,
            plugin=row.plugin,
            enabled=bool(row.enabled),
            updated_by=row.updated_by or "",
            updated_at=row.updated_at or "",
        )
        for row in found
    ]


async def save(tenant: str, plugin: str, enabled: bool, *, by: str = "") -> None:
    """记一条租户决定。写不进去就抛——静默失败会让开关看起来生效了。"""
    if _uses_file_backend():
        _save_file(tenant, plugin, enabled)
        return
    from sqlalchemy import select

    from engine.db.engine import async_session_factory
    from engine.db.models.plugin_tenancy import PluginTenancy

    async with async_session_factory() as session:
        existing = (
            await session.execute(
                select(PluginTenancy).where(
                    PluginTenancy.tenant == (tenant or ""),
                    PluginTenancy.plugin == plugin,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                PluginTenancy(
                    tenant=tenant or "",
                    plugin=plugin,
                    enabled=bool(enabled),
                    updated_by=by,
                    updated_at=_now(),
                )
            )
        else:
            existing.enabled = bool(enabled)
            existing.updated_by = by
            existing.updated_at = _now()
        await session.commit()


def _save_file(tenant: str, plugin: str, enabled: bool) -> None:
    import json

    path = _file_path()
    data: dict[str, dict[str, Any]] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = {}
    data.setdefault(tenant or "", {})[plugin] = bool(enabled)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


async def forget(tenant: str, plugin: str) -> bool:
    """删掉一条租户决定,回到"跟随平台默认"。"""
    if _uses_file_backend():
        current = _load_file(tenant)
        if plugin not in current:
            return False
        current.pop(plugin)
        _save_file_tenant(tenant, current)
        return True
    from sqlalchemy import delete as sql_delete

    from engine.db.engine import async_session_factory
    from engine.db.models.plugin_tenancy import PluginTenancy

    async with async_session_factory() as session:
        result = await session.execute(
            sql_delete(PluginTenancy).where(
                PluginTenancy.tenant == (tenant or ""), PluginTenancy.plugin == plugin
            )
        )
        await session.commit()
    return bool(result.rowcount)


def _save_file_tenant(tenant: str, values: dict[str, bool]) -> None:
    import json

    path = _file_path()
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = {}
    if values:
        data[tenant or ""] = dict(values)
    else:
        data.pop(tenant or "", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


__all__ = [
    "TABLE",
    "TenancyRow",
    "TenancyUnavailable",
    "ensure_schema",
    "forget",
    "load_tenancy",
    "rows",
    "save",
]
