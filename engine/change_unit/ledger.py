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

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
