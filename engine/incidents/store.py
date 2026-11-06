# engine/incidents/store.py
"""事故报告 —— 这一次到底发生了什么、结论是什么。

账本回答"哪几处被改了",事故回答"这一场怎么了"。两者共用 incident_id,
但报告没有句柄、没有窗口、撤不了,所以不放进账本:混在一起,每条账本查询
都得记得把它筛掉,而"记得"迟早会漏。

两个后端与账本一致:db 默认,file 给演示与离线调试;由同一个配置决定。
file 模式下报告落在账本文件同目录的 incidents.jsonl。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

STATUS_OPEN = "open"
STATUS_CLOSED = "closed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@runtime_checkable
class IncidentStore(Protocol):
    async def open(
        self, *, incident_id: str, tenant: str, signal: dict[str, Any], started_at: str = ""
    ) -> dict: ...

    async def close(
        self, incident_id: str, *, report: dict[str, Any], finished_at: str = ""
    ) -> dict | None: ...

    async def get(self, incident_id: str, tenant: str | None = None) -> dict | None: ...

    async def list(self, tenant: str | None = None, limit: int = 50) -> list[dict]: ...


def _blank(
    incident_id: str, tenant: str, signal: dict[str, Any], started_at: str
) -> dict[str, Any]:
    return {
        "id": incident_id,
        "tenant": tenant,
        "signal_source": str(signal.get("source") or ""),
        "signal_title": str(signal.get("title") or "")[:512],
        "status": STATUS_OPEN,
        "source": "",
        "started_at": started_at or _now(),
        "finished_at": "",
        "summary": "",
        "counts": {},
        "steps": [],
        "exhausted": False,
    }


def _apply_report(row: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out.update(
        {
            "status": STATUS_CLOSED,
            "source": str(report.get("source") or ""),
            "summary": str(report.get("summary") or ""),
            "counts": dict(report.get("counts") or {}),
            "steps": list(report.get("steps") or []),
            "exhausted": bool(report.get("exhausted")),
        }
    )
    return out


class JsonlIncidentStore:
    """一行一个事件,按 id 折叠出当前状态。只配演示与离线调试。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _append(self, row: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _folded(self) -> dict[str, dict[str, Any]]:
        folded: dict[str, dict[str, Any]] = {}
        for row in self._read():
            incident_id = row.get("id")
            if incident_id:
                folded[incident_id] = row
        return folded

    async def open(
        self, *, incident_id: str, tenant: str, signal: dict[str, Any], started_at: str = ""
    ) -> dict[str, Any]:
        row = _blank(incident_id, tenant, signal, started_at)
        self._append(row)
        return row

    async def close(
        self, incident_id: str, *, report: dict[str, Any], finished_at: str = ""
    ) -> dict[str, Any] | None:
        current = self._folded().get(incident_id)
        if current is None:
            return None
        row = _apply_report(current, report)
        row["finished_at"] = finished_at or _now()
        self._append(row)
        return row

    async def get(self, incident_id: str, tenant: str | None = None) -> dict[str, Any] | None:
        row = self._folded().get(incident_id)
        if row is None:
            return None
        if tenant is not None and row.get("tenant") != tenant:
            return None
        return row

    async def list(self, tenant: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        rows = [
            row
            for row in self._folded().values()
            if tenant is None or row.get("tenant") == tenant
        ]
        rows.sort(key=lambda row: row.get("started_at", ""), reverse=True)
        return rows[: max(0, limit)]


class DbIncidentStore:
    def __init__(self, session_factory: Any = None) -> None:
        if session_factory is None:
            from engine.db.engine import async_session_factory

            session_factory = async_session_factory
        self._session_factory = session_factory

    async def open(
        self, *, incident_id: str, tenant: str, signal: dict[str, Any], started_at: str = ""
    ) -> dict[str, Any]:
        from engine.db.models.incident import Incident

        row = _blank(incident_id, tenant, signal, started_at)
        async with self._session_factory() as session:
            session.add(Incident(**row))
            await session.commit()
        return row

    async def close(
        self, incident_id: str, *, report: dict[str, Any], finished_at: str = ""
    ) -> dict[str, Any] | None:
        from sqlalchemy import select

        from engine.db.models.incident import Incident

        async with self._session_factory() as session:
            found = await session.get(Incident, incident_id)
            if found is None:
                return None
            found.status = STATUS_CLOSED
            found.source = str(report.get("source") or "")
            found.summary = str(report.get("summary") or "")
            found.counts = dict(report.get("counts") or {})
            found.steps = list(report.get("steps") or [])
            found.exhausted = bool(report.get("exhausted"))
            found.finished_at = finished_at or _now()
            await session.commit()
            return _row_of(found)

    async def get(self, incident_id: str, tenant: str | None = None) -> dict[str, Any] | None:
        from engine.db.models.incident import Incident

        async with self._session_factory() as session:
            found = await session.get(Incident, incident_id)
            if found is None:
                return None
            if tenant is not None and found.tenant != tenant:
                return None
            return _row_of(found)

    async def list(self, tenant: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        from sqlalchemy import select

        from engine.db.models.incident import Incident

        stmt = select(Incident).order_by(Incident.started_at.desc()).limit(max(0, limit))
        if tenant is not None:
            stmt = stmt.where(Incident.tenant == tenant)
        async with self._session_factory() as session:
            return [_row_of(row) for row in (await session.execute(stmt)).scalars().all()]


def _row_of(model: Any) -> dict[str, Any]:
    return {
        "id": model.id,
        "tenant": model.tenant,
        "signal_source": model.signal_source,
        "signal_title": model.signal_title,
        "status": model.status,
        "source": model.source,
        "started_at": model.started_at,
        "finished_at": model.finished_at,
        "summary": model.summary,
        "counts": dict(model.counts or {}),
        "steps": list(model.steps or []),
        "exhausted": bool(model.exhausted),
    }


def create_incident_store() -> IncidentStore:
    """按配置挑实现,与账本用的是同一个开关。"""
    from engine.shared.config import config

    if config.settings.change_ledger_backend == "file":
        ledger = Path(config.settings.change_ledger_path)
        return JsonlIncidentStore(ledger.with_name("incidents.jsonl"))

    return DbIncidentStore()


async def ensure_schema() -> None:
    """建表(已存在就跳过)。与其它模型同一种做法。"""
    from engine.db.engine import engine
    from engine.db.models.incident import Incident

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Incident.__table__.create(c, checkfirst=True))


__all__ = [
    "IncidentStore",
    "JsonlIncidentStore",
    "DbIncidentStore",
    "create_incident_store",
    "ensure_schema",
    "STATUS_OPEN",
    "STATUS_CLOSED",
]
