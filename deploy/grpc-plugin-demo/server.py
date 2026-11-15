# deploy/grpc-plugin-demo/server.py
"""进程外插件示例:实现 proto PluginService 的最小服务端。

跑起来:

    pip install grpcio protobuf
    python deploy/grpc-plugin-demo/server.py            # 默认 127.0.0.1:50055

它做的事很无聊但足够真:数一遍某个目录里的 TODO 标记,把结果按能力任务返回。
值得看的是形状——插件的进程边界只在 `endpoint` 那一行,能力、任务名、Hook 全在
plugin.yaml 里声明。同一份清单,进程内与进程外走同一条注册路径。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent import futures
from pathlib import Path

import grpc

# 桩由仓库生成(scripts/gen_grpc_stubs.py)。示例故意不假设安装方式:
# 在仓库根跑时用仓库里的那份,独立部署时把它拷到旁边即可。
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from engine.plugin_manager.grpc_proto import plugin_pb2, plugin_pb2_grpc  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("demo-plugin")

MARKERS = ("TODO", "FIXME", "XXX")


def scan_todos(params: dict) -> dict:
    """数一个目录里的待办标记。不做网络,不碰下游,失败只影响这一次调用。"""
    root = Path(str(params.get("path") or ".")).expanduser()
    if not root.is_dir():
        return {"status": "error", "message": f"不是目录:{root}"}
    hits: list[dict[str, object]] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in {".git", ".venv", "node_modules"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = [
            {"path": str(path.relative_to(root)), "line": number, "text": line.strip()[:120]}
            for number, line in enumerate(text.splitlines(), 1)
            if any(marker in line for marker in MARKERS)
        ]
        hits.extend(lines)
    return {"status": "ok", "count": len(hits), "hits": hits[:20]}


class DemoPlugin(plugin_pb2_grpc.PluginServiceServicer):
    def Startup(self, request, context):
        info = request.plugin_info
        logger.info("startup: %s v%s (%d capabilities)", info.name, info.version, len(info.capabilities))
        return plugin_pb2.StartupResponse(success=True, message="demo ready")

    def Shutdown(self, request, context):
        logger.info("shutdown requested")
        return plugin_pb2.ShutdownResponse(success=True)

    def HealthCheck(self, request, context):
        return plugin_pb2.HealthResponse(healthy=True, message="demo ok")

    def RegisterScope(self, request, context):
        # 示例不声明配置;真插件在这里把 scope 报给核心,由核心回填配置值。
        return plugin_pb2.RegisterScopeResponse(success=False, message="demo 没有配置项")

    def GetScopeConfig(self, request, context):
        return plugin_pb2.GetScopeConfigResponse(
            success=False, missing_required=["demo 没有配置项"]
        )

    def HandleEvent(self, request, context):
        logger.info("event: %s", request.event)
        return plugin_pb2.EventResponse(
            success=True, result=json.dumps({"status": "ignored", "event": request.event}).encode()
        )

    def ExecuteTask(self, request, context):
        params = json.loads(request.params.decode("utf-8")) if request.params else {}
        logger.info("task: %s params=%s", request.task, params)
        if request.task == "scan_todos":
            result = scan_todos(params)
        else:
            # 未知任务如实说失败:远端"成功但什么都没做"比失败更难查
            return plugin_pb2.TaskResponse(success=False, error=f"Unknown task: {request.task}")
        return plugin_pb2.TaskResponse(
            success=result.get("status") == "ok",
            result=json.dumps(result, ensure_ascii=False).encode("utf-8"),
            error=result.get("message", ""),
        )

    def HandleHook(self, request, context):
        # 示例不订阅 Hook;被调到时保持"允许"+原样返回,不篡改载荷。
        payload = json.loads(request.payload.decode("utf-8")) if request.payload else {}
        return plugin_pb2.HookResponse(
            allowed=True, payload=json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )


def serve(host: str, port: int) -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    plugin_pb2_grpc.add_PluginServiceServicer_to_server(DemoPlugin(), server)
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    logger.info("demo plugin listening on %s:%s", host, port)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(0)


def main() -> int:
    parser = argparse.ArgumentParser(description="进程外插件示例")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=50055)
    args = parser.parse_args()
    serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
