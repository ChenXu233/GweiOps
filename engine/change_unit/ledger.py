# engine/change_unit/ledger.py
"""变更账本 —— 追加写,不改写。

两个实现共用一套异步接口:文件账本用于演示与离线调试,业务库账本用于生产。
接口是异步的,因为生产实现要写库;文件实现内部仍是同步 IO。

tenant 参数是查询范围,不是鉴权:调用方声明自己要看谁,平台不替他判断。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .model import ChangeUnit


@runtime_checkable
class Ledger(Protocol):
    async def append(self, unit: ChangeUnit) -> None: ...

    async def find(self, idempotency_key: str, tenant: str | None = None) -> dict | None: ...

    async def read(self, tenant: str | None = None) -> list[dict[str, Any]]: ...

    async def latest(
        self, tenant: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]: ...

    async def history(
        self, unit_id: str, tenant: str | None = None
    ) -> list[dict[str, Any]]: ...


class JsonlLedger:
    """首版账本:一行一个事件,落一个本地文件。并发写与租户隔离都靠不住,只配演示。"""

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

    async def append(self, unit: ChangeUnit) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(unit.to_dict(), ensure_ascii=False) + "\n")

    async def find(self, idempotency_key: str, tenant: str | None = None) -> dict | None:
        """按幂等键找最近一条记录;重放判定只看账本,不看内存。"""
        if not idempotency_key:
            return None
        for row in reversed(self._read()):
            if row.get("idempotency_key") != idempotency_key:
                continue
            if tenant is not None and row.get("tenant") != tenant:
                continue
            return row
        return None

    async def read(self, tenant: str | None = None) -> list[dict[str, Any]]:
        rows = self._read()
        if tenant is None:
            return rows
        return [row for row in rows if row.get("tenant") == tenant]

    async def latest(
        self, tenant: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """按 unit id 折叠出当前状态,最新的在前。

        账本是追加日志:同一个单元的执行与撤销各是一行,当前状态永远看最后一行。
        """
        folded: dict[str, dict[str, Any]] = {}
        for row in self._read():
            if tenant is not None and row.get("tenant") != tenant:
                continue
            unit_id = row.get("id")
            if unit_id:
                folded[unit_id] = row
        rows = list(reversed(list(folded.values())))
        return rows if limit is None else rows[: max(0, limit)]

    async def history(
        self, unit_id: str, tenant: str | None = None
    ) -> list[dict[str, Any]]:
        return [
            row
            for row in self._read()
            if row.get("id") == unit_id
            and (tenant is None or row.get("tenant") == tenant)
        ]


def create_ledger() -> Ledger:
    """按配置挑实现。db 是默认;file 留给没有 Postgres 的演示与离线调试。"""
    from engine.shared.config import config

    if config.settings.change_ledger_backend == "file":
        return JsonlLedger(config.settings.change_ledger_path)

    from engine.db.change_ledger import DbLedger

    return DbLedger()


__all__ = ["Ledger", "JsonlLedger", "create_ledger"]
