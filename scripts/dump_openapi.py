# scripts/dump_openapi.py
"""导出 API 契约到 contracts/openapi.json。

这是前端类型的唯一来源:前端跑 `pnpm gen:api` 读这个文件生成 TypeScript,
所以改了引擎的响应模型之后必须重跑一次,否则前端拿到的还是旧形状。

    python scripts/dump_openapi.py

不需要 Postgres 也不需要起服务:只导入 app 取它的 OpenAPI 文档。
输出按 key 排序,同样的代码永远得到同样的字节,提交时 diff 只有真实变化。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "contracts" / "openapi.json"


def build() -> dict:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from engine.api.app import app

    return app.openapi()


def main() -> int:
    spec = build()
    payload = json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(payload, encoding="utf-8")

    schemas = spec.get("components", {}).get("schemas", {})
    print(
        f"wrote {OUT.relative_to(ROOT)}: "
        f"{len(spec.get('paths', {}))} paths, {len(schemas)} schemas, {len(payload)} bytes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
