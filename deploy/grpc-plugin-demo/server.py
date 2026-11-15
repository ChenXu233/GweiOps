# deploy/grpc-plugin-demo/server.py
"""进程外插件示例:数一个目录里的待办标记。

跑起来:

    uv run --project engine python deploy/grpc-plugin-demo/server.py   # 127.0.0.1:50055

值得看的是形状:插件只管业务方法,协议由 `grpc_server` 兜住;能力名、任务名映射
全在 plugin.yaml 里声明。同一份清单,进程内与进程外走同一条注册路径。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from engine.plugin_manager.grpc_server import serve  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MARKERS = ("TODO", "FIXME", "XXX")
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__"}


SOURCES = ("*.py", "*.ts", "*.vue", "*.md", "*.yaml", "*.yml")


def scan_todos(params: dict) -> dict:
    """数一个目录里的待办标记。不碰网络,失败只影响这一次调用。

    结果里带 `scanned`:0 个命中时,人得能分清"扫过了没有待办"与"什么都没扫到"。
    """
    root = Path(str(params.get("path") or ".")).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"不是目录:{root}")
    hits: list[dict[str, object]] = []
    scanned = 0
    for pattern in SOURCES:
        for path in sorted(root.rglob(pattern)):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            scanned += 1
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if any(marker in line for marker in MARKERS):
                    hits.append(
                        {
                            "path": str(path.relative_to(root)),
                            "line": number,
                            "text": line.strip()[:120],
                        }
                    )
    return {"status": "ok", "count": len(hits), "scanned": scanned, "hits": hits[:20]}


class DemoPlugin:
    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event: str, data: dict) -> dict:
        return {"status": "ignored", "event": event}

    async def execute_task(self, task: str, params: dict) -> dict:
        if task == "scan_todos":
            return scan_todos(params)
        # 未知任务如实抛:远端"成功但什么都没做"比失败更难查
        raise ValueError(f"Unknown task: {task}")


def main() -> int:
    parser = argparse.ArgumentParser(description="进程外插件示例")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=50055)
    args = parser.parse_args()
    serve(DemoPlugin(), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
