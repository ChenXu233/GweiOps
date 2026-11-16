# deploy/grpc-plugin-demo/server.py
"""进程外插件示例:数一个目录里的待办标记,并演示效果四方法与配置下发。

跑起来:

    uv run --project engine python deploy/grpc-plugin-demo/server.py   # 127.0.0.1:50055

值得看的是形状:插件只管业务方法,协议由 `grpc_server` 兜住;能力名、任务名映射、
效果四方法、要哪些配置全在 plugin.yaml 里声明。同一份清单,进程内与进程外走同一条
注册路径。

`scan.todos` 是一次**效果**(不是只读能力):它在目标目录里落一个标记文件,句柄就是
那个文件的名字,撤销 = 删掉它。这样"进程外插件能不能当效果提供者"这件事在这里是
可验证的,而不是一句文档。
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from engine.change_unit import Effect, EffectNotApplied, Window  # noqa: E402
from engine.plugin_manager.grpc_server import serve  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

MARKERS = ("TODO", "FIXME", "XXX")
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__"}

SOURCES = ("*.py", "*.ts", "*.vue", "*.md", "*.yaml", "*.yml")

# 印记文件名里带句柄:撤销只删这一颗,不碰别人留下的
MARKER_SUFFIX = ".gwei-scan.json"

SCOPE = "demo-remote-scan"


def count_todos(root: Path) -> dict:
    """数一个目录里的待办标记。不碰网络,失败只影响这一次调用。

    结果里带 `scanned`:0 个命中时,人得能分清"扫过了没有待办"与"什么都没扫到"。
    """
    if not root.is_dir():
        # 确定没碰到任何东西:核心据此把单元记成可重试,而不是"不知道动没动"
        raise EffectNotApplied(f"不是目录:{root}")
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
    """一个最小但完整的效果提供者。

    句柄是不透明字符串:核心存下来再原样带回来,从不解开。所以这里可以把它当
    文件名用,断点续传靠它。
    """

    def __init__(self) -> None:
        # 核心推下来的配置。进程外插件读不到核心的环境变量与库,值只能从这条 RPC 过来。
        self.settings: dict[str, str] = {}
        self.missing: list[str] = []

    # -- 生命周期 ---------------------------------------------------

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    async def health_check(self) -> bool:
        return True

    async def configure(self, scope: str, values: dict, missing: list[str]) -> None:
        """核心把配置推下来。收下就行,校验不过就抛——它会如实报给人。"""
        if scope != SCOPE:
            return  # 别的 scope 不是给我的
        self.settings = dict(values)
        self.missing = list(missing)
        logging.info("configure %s: %d 项,%d 项缺失", scope, len(values), len(missing))

    # -- 能力 -------------------------------------------------------

    async def handle_event(self, event: str, data: dict) -> dict:
        return {"status": "ignored", "event": event}

    async def execute_task(self, task: str, params: dict) -> dict:
        """没写效果四方法时的兜底分发。这个示例另外实现了那四个,所以走不到这里。"""
        if task == "scan_todos":
            return count_todos(Path(str(params.get("path") or ".")).expanduser())
        # 未知任务如实抛:远端"成功但什么都没做"比失败更难查
        raise ValueError(f"Unknown task: {task}")

    # -- 效果四方法(与进程内提供者同名同签名)-------------------------

    async def execute(self, task: str, args: dict) -> dict:
        root = Path(str(args.get("path") or ".")).expanduser()
        report = count_todos(root)
        # 落一个印记:这就是这次变更的凭证,句柄指向它
        handle = f"{uuid.uuid4().hex}{MARKER_SUFFIX}"
        marker = root / handle
        marker.write_text(
            f'{{"count": {report["count"]}, "scanned": {report["scanned"]}, '
            f'"note": "{self.settings.get("note", "")}"}}\n',
            encoding="utf-8",
        )
        return {"status": "ok", "handle": handle, **report}

    async def undo(self, task: str, args: dict, handle: str) -> dict:
        root = Path(str(args.get("path") or ".")).expanduser()
        target = root / handle
        if not target.exists():
            # 印记已经不在了:撤销是幂等的,不是失败
            return {"removed": False, "handle": handle}
        target.unlink()
        return {"removed": True, "handle": handle}

    async def window(self, effect: Effect, handle: str | None) -> Window:
        """执行前问"做完还撤得回来吗",执行后问"现在还撤得回来吗"。

        撤销是对称的(删掉自己落的印记),所以只要目标目录还在就一直能撤。
        """
        root = Path(str(effect.args.get("path") or ".")).expanduser()
        if not root.is_dir():
            return Window(source="目标目录不存在")
        return Window(unbounded=True, source="marker_present")

    async def verify(self, effect: Effect, handle: str) -> tuple[bool, dict]:
        root = Path(str(effect.args.get("path") or ".")).expanduser()
        marker = root / str(handle or "")
        ok = marker.is_file()
        return ok, {"marker": str(handle), "found": ok, "at": time.time()}


def main() -> int:
    parser = argparse.ArgumentParser(description="进程外插件示例")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=50055)
    args = parser.parse_args()
    serve(DemoPlugin(), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
