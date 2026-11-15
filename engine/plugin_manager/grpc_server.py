# engine/plugin_manager/grpc_server.py
"""给进程外插件作者用的服务端骨架 —— 只实现业务方法,协议细节在这里。

不写这个包的话,每个插件都要自己:定义 servicer、把 JSON 编解码写在每个 RPC 里、
把返回值塞进对应的 protobuf 消息。那些都是机械劳动,而且每写一遍就多一处不一致。

用法:

    from engine.plugin_manager.grpc_server import serve

    class MyPlugin:
        capabilities = ["scan.dependencies"]

        async def execute_task(self, task, params):
            return {"status": "ok"}

        async def handle_event(self, event, data):
            return {"status": "ignored"}

    serve(MyPlugin(), port=50051)

任务名、能力名、Hook 订阅都由 `plugin.yaml` 声明,插件只需要实现方法本身。
"""

from __future__ import annotations

import json
import logging
from concurrent import futures
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class PluginHandlers(Protocol):
    """插件要实现的东西。全部可选之外的都没实现时按"不做"回。"""

    async def execute_task(self, task: str, params: dict) -> dict: ...

    async def handle_event(self, event: str, data: dict) -> dict: ...


def _dumps(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")


def _loads(raw: bytes) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"载荷不是 JSON: {e}") from e
    return data if isinstance(data, dict) else {"value": data}


def build_servicer(plugin: Any):
    """把一个实现了 execute_task/handle_event/handle_hook 的对象包成 gRPC servicer。

    同步调用在 grpc 的线程池里跑;插件方法若是协程,这里用一个临时事件循环跑完。
    插件不必关心自己被哪种方式调用。
    """
    import asyncio

    from .grpc_proto import plugin_pb2, plugin_pb2_grpc

    def run(value):
        if asyncio.iscoroutine(value):
            return asyncio.run(value)
        return value

    class Servicer(plugin_pb2_grpc.PluginServiceServicer):
        def Startup(self, request, context):
            info = request.plugin_info
            logger.info(
                "startup: %s v%s (%d capabilities)",
                info.name,
                info.version,
                len(info.capabilities),
            )
            hook = getattr(plugin, "on_startup", None)
            if hook is not None:
                try:
                    run(hook())
                except Exception as e:  # noqa: BLE001 - 插件自己的启动失败,如实回
                    logger.error("plugin on_startup failed: %s", e)
                    return plugin_pb2.StartupResponse(success=False, message=str(e))
            return plugin_pb2.StartupResponse(success=True, message="ok")

        def Shutdown(self, request, context):
            hook = getattr(plugin, "on_shutdown", None)
            if hook is not None:
                try:
                    run(hook())
                except Exception as e:  # noqa: BLE001
                    logger.warning("plugin on_shutdown failed: %s", e)
            return plugin_pb2.ShutdownResponse(success=True)

        def HealthCheck(self, request, context):
            hook = getattr(plugin, "health_check", None)
            if hook is None:
                return plugin_pb2.HealthResponse(healthy=True, message="ok")
            try:
                healthy = bool(run(hook()))
            except Exception as e:  # noqa: BLE001 - 探活本身不该把服务掀翻
                return plugin_pb2.HealthResponse(healthy=False, message=str(e))
            return plugin_pb2.HealthResponse(healthy=healthy, message="ok")

        def RegisterScope(self, request, context):
            return plugin_pb2.RegisterScopeResponse(
                success=False, message="配置由清单声明;这里没有额外 scope"
            )

        def GetScopeConfig(self, request, context):
            return plugin_pb2.GetScopeConfigResponse(success=False)

        def HandleEvent(self, request, context):
            try:
                data = _loads(request.data)
                result = run(plugin.handle_event(request.event, data))
            except Exception as e:  # noqa: BLE001 - 远端自己的错,回给核心去记
                return plugin_pb2.EventResponse(success=False, error=str(e))
            return plugin_pb2.EventResponse(success=True, result=_dumps(result or {}))

        def ExecuteTask(self, request, context):
            try:
                params = _loads(request.params)
                result = run(plugin.execute_task(request.task, params))
            except Exception as e:  # noqa: BLE001
                return plugin_pb2.TaskResponse(success=False, error=str(e))
            return plugin_pb2.TaskResponse(success=True, result=_dumps(result or {}))

        def HandleHook(self, request, context):
            handler = getattr(plugin, "handle_hook", None)
            payload = _loads(request.payload)
            if handler is None:
                # 没订阅 Hook 的插件被问到,保持"允许 + 原样返回":它不该改变载荷
                return plugin_pb2.HookResponse(allowed=True, payload=_dumps(payload))
            try:
                result = run(handler(request.point, payload))
            except Exception as e:  # noqa: BLE001
                return plugin_pb2.HookResponse(allowed=False, error=str(e))
            if result is False:
                return plugin_pb2.HookResponse(allowed=False)
            if result is None:
                # observe:没有新载荷可回
                return plugin_pb2.HookResponse(allowed=True)
            return plugin_pb2.HookResponse(allowed=True, payload=_dumps(result))

    return Servicer()


def serve(plugin: Any, *, host: str = "127.0.0.1", port: int = 50051, workers: int = 4):
    """起服务并阻塞。Ctrl+C 干净退出。"""
    import grpc

    from .grpc_proto import plugin_pb2_grpc

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=workers))
    plugin_pb2_grpc.add_PluginServiceServicer_to_server(build_servicer(plugin), server)
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    logger.info("plugin listening on %s:%s", host, port)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("plugin stopping")
        server.stop(0)


__all__ = ["PluginHandlers", "build_servicer", "serve"]
