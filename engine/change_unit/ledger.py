# engine/change_unit/ledger.py
"""变更账本 —— 追加写,不改写。首版是文件账本,业务库接入前足够审计。"""

from __future__ import annotations

import json
from pathlib import Path

from .model import ChangeUnit


class JsonlLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, unit: ChangeUnit) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(unit.to_dict(), ensure_ascii=False) + "\n")

    def find(self, idempotency_key: str) -> dict | None:
        """按幂等键找最近一条记录;重放判定只看账本,不看内存。"""
        if not idempotency_key:
            return None
        for row in reversed(self.read()):
            if row.get("idempotency_key") == idempotency_key:
                return row
        return None

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def latest(self) -> list[dict]:
        """按 unit id 折叠出当前状态,最新的在前。

        账本是追加日志:同一个单元的执行与撤销各是一行,当前状态永远看最后一行。
        """
        folded: dict[str, dict] = {}
        for row in self.read():
            unit_id = row.get("id")
            if unit_id:
                folded[unit_id] = row
        return list(reversed(list(folded.values())))

    def history(self, unit_id: str) -> list[dict]:
        """一个单元的全部事件,按写入顺序。"""
        return [row for row in self.read() if row.get("id") == unit_id]
