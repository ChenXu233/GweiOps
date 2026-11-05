# tests/test_integration/test_openapi_contract.py
"""契约不漂移:仓库里的 contracts/openapi.json 必须与 app 当前生成的一致。

前端类型是从这个文件生成的(pnpm --filter @gwei/core gen:api),
文件过期就等于前端拿到旧形状。改了任何响应模型之后跑:

    python scripts/dump_openapi.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "openapi.json"


def test_committed_contract_matches_app() -> None:
    from engine.api.app import app

    spec = app.openapi()
    expected = json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=True) + chr(10)
    actual = CONTRACT.read_text(encoding="utf-8")
    assert actual == expected, (
        "contracts/openapi.json 与当前接口不一致,运行 python scripts/dump_openapi.py 重新生成"
    )


def test_contract_covers_frontend_endpoints() -> None:
    """前端在用的端点必须都在契约里,否则生成的客户端会缺接口。"""
    spec = json.loads(CONTRACT.read_text(encoding="utf-8"))
    paths = set(spec.get("paths", {}))

    required = {
        "/api/health",
        "/api/dashboard",
        "/api/dashboard/pending",
        "/api/dashboard/overnight",
        "/api/dashboard/canary",
        "/api/issues",
        "/api/issues/{issue_id}",
        "/api/repos",
        "/api/settings",
        "/api/runs",
        "/api/metrics",
        "/api/plugins",
        "/api/plugins/widgets",
        "/api/changes",
        "/api/changes/{unit_id}",
        "/api/changes/{unit_id}/approve",
        "/api/changes/{unit_id}/veto",
        "/api/changes/{unit_id}/rollback",
    }
    missing = required - paths
    assert not missing, f"契约里缺少前端在用的端点: {sorted(missing)}"
