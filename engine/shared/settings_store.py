# engine/shared/settings_store.py
"""配置值的落库层 —— 让"填一次"能活过重启,并且按租户分开。

和账本、事故一样两个后端:db 默认,file 给演示与离线调试。选哪个由同一个开关决定。
读回来的是 {租户: {scope: {键: 值}}};租户为空串是公共值。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

GLOBAL_TENANT = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@runtime_checkable
class SettingsStore(Protocol):
    async def load(self) -> dict[str, dict[str, dict[str, str]]]: ...

    async def put(
        self, scope: str, values: dict[str, str], by: str = "", tenant: str = ""
    ) -> dict[str, str]: ...

    async def delete(self, scope: str, key: str, tenant: str = "") -> bool: ...


class JsonlSettingsStore:
    """一个 JSON 文件装全部租户与 scope。只配演示与离线调试。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _read(self) -> dict[str, dict[str, dict[str, str]]]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}

    def _write(self, data: dict[str, dict[str, dict[str, str]]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )

    async def load(self) -> dict[str, dict[str, dict[str, str]]]:
        return self._read()

    async def put(
        self, scope: str, values: dict[str, str], by: str = "", tenant: str = ""
    ) -> dict[str, str]:
        data = self._read()
        bucket = data.setdefault(tenant or GLOBAL_TENANT, {}).setdefault(scope, {})
        for key, value in values.items():
            bucket[str(key)] = str(value)
        self._write(data)
        return dict(bucket)

    async def delete(self, scope: str, key: str, tenant: str = "") -> bool:
        data = self._read()
        bucket_tenant = data.get(tenant or GLOBAL_TENANT, {})
        bucket = bucket_tenant.get(scope)
        if not bucket or str(key) not in bucket:
            return False
        bucket.pop(str(key))
        if not bucket:
            bucket_tenant.pop(scope, None)
        if not bucket_tenant:
            data.pop(tenant or GLOBAL_TENANT, None)
        self._write(data)
        return True


class DbSettingsStore:
    def __init__(self, session_factory: Any = None) -> None:
        if session_factory is None:
            from engine.db.engine import async_session_factory

            session_factory = async_session_factory
        self._session_factory = session_factory

    async def load(self) -> dict[str, dict[str, dict[str, str]]]:
        from sqlalchemy import select

        from engine.db.models.plugin_setting import PluginSetting

        async with self._session_factory() as session:
            rows = (await session.execute(select(PluginSetting))).scalars().all()
        out: dict[str, dict[str, dict[str, str]]] = {}
        for row in rows:
            out.setdefault(row.tenant, {}).setdefault(row.scope, {})[row.key] = row.value
        return out

    async def put(
        self, scope: str, values: dict[str, str], by: str = "", tenant: str = ""
    ) -> dict[str, str]:
        from sqlalchemy import select

        from engine.db.models.plugin_setting import PluginSetting

        tenant = tenant or GLOBAL_TENANT
        stamp = _now()
        async with self._session_factory() as session:
            existing = {
                row.key: row
                for row in (
                    await session.execute(
                        select(PluginSetting).where(
                            PluginSetting.tenant == tenant,
                            PluginSetting.scope == scope,
                        )
                    )
                )
                .scalars()
                .all()
            }
            for key, value in values.items():
                row = existing.get(str(key))
                if row is None:
                    session.add(
                        PluginSetting(
                            tenant=tenant,
                            scope=scope,
                            key=str(key),
                            value=str(value),
                            updated_at=stamp,
                            updated_by=by,
                        )
                    )
                else:
                    row.value = str(value)
                    row.updated_at = stamp
                    row.updated_by = by
            await session.commit()
        return {
            **{key: row.value for key, row in existing.items()},
            **{str(k): str(v) for k, v in values.items()},
        }

    async def delete(self, scope: str, key: str, tenant: str = "") -> bool:
        from sqlalchemy import delete as sql_delete

        from engine.db.models.plugin_setting import PluginSetting

        async with self._session_factory() as session:
            result = await session.execute(
                sql_delete(PluginSetting).where(
                    PluginSetting.tenant == (tenant or GLOBAL_TENANT),
                    PluginSetting.scope == scope,
                    PluginSetting.key == str(key),
                )
            )
            await session.commit()
        return bool(result.rowcount)


def create_settings_store() -> SettingsStore:
    from engine.shared.config import config

    if config.settings.change_ledger_backend == "file":
        ledger = Path(config.settings.change_ledger_path)
        return JsonlSettingsStore(ledger.with_name("settings.json"))

    return DbSettingsStore()


async def ensure_schema() -> None:
    from engine.db.engine import engine
    from engine.db.models.plugin_setting import PluginSetting

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: PluginSetting.__table__.create(c, checkfirst=True))


__all__ = [
    "SettingsStore",
    "JsonlSettingsStore",
    "DbSettingsStore",
    "create_settings_store",
    "ensure_schema",
    "GLOBAL_TENANT",
]
