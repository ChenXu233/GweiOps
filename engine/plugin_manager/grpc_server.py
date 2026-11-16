# engine/plugin_manager/grpc_server.py
"""给进程外插件作者用的服务端骨架 —— 只实现业务方法,协议细节在这里。

不写这个包的话,每个插件都要自己:定义 servicer、把 JSON 编解码写在每个 RPC 里、
把返回值塞进对应的 protobuf 消息。那些都是机械劳动,而且每写一遍就多一处不一致。

用法:

    from engine.plugin_manager.grpc_server import serve

    class MyPlugin:
        async def execute_task(self, task, params):
            return {"status": "ok"}

        async def handle_event(self, event, data):
            return {"status": "ignored"}

    serve(MyPlugin(), port=50051)

任务名、能力名、Hook 订阅、要哪些配置都由 `plugin.yaml` 声明,插件只需要实现方法本身。

**效果四方法**:声明了 `effects` 的插件,`execute_task` 会被带着不同的
`params["phase"]` 调到 —— `execute` / `undo` / `window` / `verify`。四种阶段
在这里翻译成与进程内提供者同名的方法,插件写起来跟进程内一模一样:

    class MyPlugin:
        async def execute(self, task, args): ...            -> {"handle": "..."}
        async def undo(self, task, args, handle): ...
        async def window(self, effect, handle): ...          -> Window / dict
        async def verify(self, effect, handle): ...          -> (ok, facts)

不写这四个方法也能用:那些阶段会退回同一个 `execute_task(task, params)`,
`params` 里带着 `phase` / `effect` / `handle`,自己分派即可。

**失败语义**:抛 `EffectNotApplied` 表示"确定没碰到下游",核心把单元记成可重试的
failed;抛别的异常记成 unknown。这个区分只有插件知道自己那一层发生了什么。
"""

from __future__ import annotations

import dataclasses
import json
import logging
from concurrent import futures
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class PluginHandlers(Protocol):
    """插件要实现的业务方法;没实现的按"不做"回。"""

    async def execute_task(self, task: str, params: dict) -> dict: ...

    async def handle_event(self, event: str, data: dict) -> dict: ...


def _plain(value: Any) -> Any:
    """返回值可能是 Window / tuple / pydantic 对象:先摊成 JSON 认得的形状。

    Window 摊平而不是转字符串:`{"seconds": n}` 与 `{"unbounded": true}` 是核心
    判"还能撤多久"的唯一依据,摊坏了就等于说"读不到窗口"。
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _dumps(value: Any) -> bytes:
    return json.dumps(_plain(value), ensure_ascii=False, default=str).encode("utf-8")


def _is_not_applied(exc: BaseException) -> bool:
    """插件说得出"下游确定没动"吗。按类名认,免得插件为了继承它去依赖引擎。"""
    from engine.change_unit.errors import EffectNotApplied

    return isinstance(exc, EffectNotApplied)


def _task_response(exc: BaseException, plugin_pb2):
    from .grpc_loader import NOT_APPLIED

    if _is_not_applied(exc):
        return plugin_pb2.TaskResponse(success=False, error=str(exc), error_kind=NOT_APPLIED)
    return plugin_pb2.TaskResponse(success=False, error=str(exc))


def _loads(raw: bytes) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"载荷不是 JSON: {e}") from e
    return data if isinstance(data, dict) else {"value": data}


def _effect(payload: dict):
    """wire 上的效果 → Effect。

    远端拿到的必须是**与进程内同一个类型**,不然 window / verify 里
    `effect.capability`、`effect.args` 这些写法一搬过来就全要改。
    """
    from engine.change_unit.model import Effect

    return Effect(
        task=str(payload.get("task") or ""),
        args=dict(payload.get("args") or {}),
        undo_task=str(payload.get("undo_task") or ""),
        undo_kind=str(payload.get("undo_kind") or "retained"),
        label=str(payload.get("label") or ""),
        capability=str(payload.get("capability") or ""),
        verify=tuple(
            dict(rule) for rule in (payload.get("verify") or ()) if isinstance(rule, dict)
        ),
    )


def _dispatch_phase(plugin: Any, phase: str, task: str, params: dict) -> Any:
    """按阶段找插件的方法;没有就交回 execute_task 自己分派。

    window / verify 拿到的是 effect(整条声明)与 handle,不是散装参数:进程内
    提供者的签名就是这样,远端照抄一份,迁移过来不用改逻辑。
    """
    method = getattr(plugin, phase, None) if phase else None
    if phase == "execute" and method is not None:
        return method(task, params.get("args") or params)
    if phase == "undo" and method is not None:
        return method(task, params.get("args") or {}, params.get("handle") or "")
    if phase in ("window", "verify") and method is not None:
        return method(_effect(params.get("effect") or {}), params.get("handle"))
    return plugin.execute_task(task, params)


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
            except Exception as e:  # noqa: BLE001 - 探活失败只影响健康状态
                return plugin_pb2.HealthResponse(healthy=False, message=str(e))
            return plugin_pb2.HealthResponse(healthy=healthy, message="ok")

        def Configure(self, request, context):
            """核心把某个 scope 的值推下来。插件把它记在自己那边就行。"""
            handler = getattr(plugin, "configure", None)
            if handler is None:
                return plugin_pb2.ConfigureResponse(
                    success=True, message="插件没有实现 configure,值留在核心"
                )
            try:
                run(
                    handler(
                        request.scope,
                        dict(request.config),
                        list(request.missing),
                    )
                )
            except Exception as e:  # noqa: BLE001 - 插件拒收要说出来,不能装作收下了
                logger.warning("plugin configure(%s) failed: %s", request.scope, e)
                return plugin_pb2.ConfigureResponse(success=False, message=str(e))
            return plugin_pb2.ConfigureResponse(success=True, message="ok")

        def HandleEvent(self, request, context):
            try:
                data = _loads(request.data)
                result = run(plugin.handle_event(request.event, data))
            except Exception as e:  # noqa: BLE001 - 远端自己的错,回给核心去记
                return plugin_pb2.EventResponse(success=False, error=str(e))
            return plugin_pb2.EventResponse(success=True, result=_dumps(result or {}))

        def ExecuteTask(self, request, context):
            """能力调用与效果四方法的共同入口,靠 metadata["phase"] 分流。

            有对应方法就交给它(插件写起来与进程内一致),没有就退回 execute_task
            并把 phase 放进 params —— 老插件不必改一行。
            """
            try:
                params = _loads(request.params)
                phase = dict(request.metadata).get("phase", "")
                if phase:
                    params = {**params, "phase": phase}
                result = run(_dispatch_phase(plugin, phase, request.task, params))
            except Exception as e:  # noqa: BLE001 - 远端自己的错,回给核心去记
                return _task_response(e, plugin_pb2)
            if isinstance(result, tuple):
                # verify 的两段返回值:核心要的是 ok 与 facts 分开的两样东西
                ok, facts = result
                result = {"ok": bool(ok), "facts": dict(facts or {})}
            return plugin_pb2.TaskResponse(success=True, result=_dumps(result or {}))

        def HandleHook(self, request, context):
            handler = getattr(plugin, "handle_hook", None)
            payload = _loads(request.payload)
            if handler is None:
                # 没订阅 Hook 的插件被问到:允许 + 原样返回
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
