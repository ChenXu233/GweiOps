# engine/plugin_manager/grpc_loader.py
"""进程外 gRPC 插件 —— 插件跑在自己的进程里,核心只持有一个代理。

形态:`plugin.yaml` 里写 `endpoint: host:port`,不写 `class_name`。声明仍旧在清单里
(能力、效果、Hook 订阅、周期),wire 只承载调用——两边因此走同一条注册路径,控制台
在对面进程没起来时也能把它讲清楚。

地址可以用环境变量覆盖,一份清单就能服务多个环境:

    PLUGINS_GRPC="scan-agent=10.0.0.5:50051,other=127.0.0.1:50052"

覆盖规则是「清单声明 endpoint」优先于「环境变量里同名条目」的默认地址;环境变量里
列出的名字即使清单没声明,也按最小清单(一个能力都没有的适配器)接上,便于临时接入。

失败隔离的边界在这里:

- 对面连不上、超时、抛错,**只影响这一个插件**——异常在代理内被翻译成本插件的失败,
  不往调用方的工作流里扔裸 grpc 异常;
- 核心侧每次调用都有超时(`PLUGINS_GRPC_TIMEOUT_S`,默认 10 秒),一个卡住的远端
  进程不会把整条工作流挂在那里。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from .base import PluginBase, PluginType
from .manifest import Manifest
from .registry import PluginRegistry, registry as default_registry

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 10.0


class GrpcPluginError(RuntimeError):
    """远端插件调用失败。调用方据此记一次失败,不当成"核心坏了"。"""


class GrpcPluginProxy(PluginBase):
    """远端 gRPC 插件的进程内代理。

    它只做一件看起来不像插件的事:把每一次调用翻成一次 RPC。清单里声明的能力名、
    任务名映射、Hook 订阅都由核心解释,代理不认识它们——远端改了实现不用改核心。
    """

    def __init__(
        self,
        manifest: Manifest,
        target: str,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        channel_factory: Any = None,
    ) -> None:
        self.manifest = manifest
        self._name = manifest.name
        self._target = target
        self._timeout_s = timeout_s
        # 声明在清单里,实例属性照抄一份:核心按实例属性解析 (租户, 目标)
        self.binding = manifest.binding
        self.tenant = manifest.tenant
        self._channel_factory = channel_factory
        self._channel = None
        self._stub = None

    # -- 与进程内插件相同的形状 ---------------------------------------

    def __repr__(self) -> str:  # 日志里认得出它是进程外的
        return f"GrpcPluginProxy({self._name} @ {self._target})"

    # -- 连接 -------------------------------------------------------

    def _ensure_stub(self):
        if self._stub is not None:
            return self._stub
        if self._channel_factory is not None:
            self._channel, self._stub = self._channel_factory(self._target)
            return self._stub
        try:
            import grpc
        except ImportError as e:  # pragma: no cover - 依赖已声明,只有裁剪安装才会缺
            raise GrpcPluginError(
                "进程外插件需要 grpcio:装 engine 的依赖即可"
            ) from e
        from .grpc_proto import plugin_pb2_grpc

        self._channel = grpc.insecure_channel(self._target)
        self._stub = plugin_pb2_grpc.PluginServiceStub(self._channel)
        return self._stub

    async def _call(self, method: str, request, *, timeout_s: float | None = None):
        """跑一次 RPC,把 grpc 的异常翻译成本插件的失败。

        远端抛的错、连不上、超时,对核心来说都是"这个插件这一次没成"——不该让
        一个坏掉的插件用 RpcError 把上层工作流的语义搅乱。
        """
        stub = self._ensure_stub()
        fn = getattr(stub, method, None)
        if fn is None:  # pragma: no cover - 只有桩版本不匹配才会走到
            raise GrpcPluginError(f"{self._name}: 远端没有实现 {method}")
        try:
            return await asyncio.to_thread(fn, request, timeout=timeout_s or self._timeout_s)
        except Exception as e:  # noqa: BLE001 - grpc 的异常类型多,一律按本插件失败处理
            kind = type(e).__name__
            logger.warning(
                "gRPC plugin %s call %s failed (%s): %s", self._name, method, kind, e
            )
            raise GrpcPluginError(f"{self._name}.{method} 失败:{kind}: {e}") from e

    # -- 生命周期 ---------------------------------------------------

    async def on_startup(self) -> None:
        """握手一次:告诉远端它是谁、要哪些配置,顺手把健康状态核一遍。

        连不上只记日志——远端此刻没起来不等于这个部署错了,下一次调用还能成。
        真的不能用时,`health_check()` 会说 false,页面上看得见。
        """
        from .grpc_proto import plugin_pb2

        request = plugin_pb2.StartupRequest(
            plugin_info=plugin_pb2.PluginInfo(
                name=self.manifest.name,
                version=self.manifest.version,
                type=_proto_type(self.manifest.type),
                description=self.manifest.description,
                capabilities=self.manifest.capabilities,
            )
        )
        try:
            response = await self._call("Startup", request)
        except GrpcPluginError as e:
            logger.warning("gRPC plugin %s 没有握手成功:%s", self._name, e)
            return
        if not response.success:
            logger.warning(
                "gRPC plugin %s 拒绝启动:%s", self._name, response.message or "(没有说明)"
            )
        else:
            logger.info("gRPC plugin %s started at %s", self._name, self._target)

    async def on_shutdown(self) -> None:
        from .grpc_proto import plugin_pb2

        try:
            if self._stub is not None:
                await self._call("Shutdown", plugin_pb2.ShutdownRequest(), timeout_s=2.0)
        except GrpcPluginError:
            pass  # 关的时候对面已经不在了,是常态
        if self._channel is not None:
            try:
                self._channel.close()
            except Exception:  # noqa: BLE001 - 关不掉也不该拦住核心退出
                pass
        self._channel = None
        self._stub = None

    async def health_check(self) -> bool:
        from .grpc_proto import plugin_pb2

        try:
            response = await self._call("HealthCheck", plugin_pb2.HealthRequest(), timeout_s=2.0)
        except GrpcPluginError:
            return False
        return bool(response.healthy)

    # -- 调用面 -----------------------------------------------------

    async def handle_event(self, event: str, data: dict) -> dict:
        from .grpc_proto import plugin_pb2

        payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        response = await self._call(
            "HandleEvent",
            plugin_pb2.EventRequest(event=event, data=payload),
        )
        return _decode_result(response, "HandleEvent")

    async def execute_task(self, task: str, params: dict) -> dict:
        from .grpc_proto import plugin_pb2

        payload = json.dumps(params, ensure_ascii=False, default=str).encode("utf-8")
        response = await self._call(
            "ExecuteTask",
            plugin_pb2.TaskRequest(task=task, params=payload),
        )
        return _decode_result(response, "ExecuteTask")

    async def handle_hook(self, point: str, payload: dict) -> Any:
        """Hook 回调。远端拿到 mode 与载荷,回 allowed / payload。

        veto 的语义靠 `allowed=False` 表达;transform 用返回的 payload;observe 的
        返回值由核心丢弃——三档语义都在核心(HookPipeline)判定,远端只回答事实。
        """
        from .grpc_proto import plugin_pb2

        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        response = await self._call(
            "HandleHook",
            plugin_pb2.HookRequest(point=point, payload=body),
        )
        if response.error:
            raise GrpcPluginError(f"{self._name}.HandleHook({point}): {response.error}")
        if not response.allowed:
            return False
        if not response.payload:
            return None
        return json.loads(response.payload.decode("utf-8"))


def make_proxy(manifest: Manifest, target: str, *, timeout_s: float | None = None) -> GrpcPluginProxy:
    """发现期建代理。超时取自环境,单点配置:所有远端插件一个口径。"""
    return GrpcPluginProxy(
        manifest, target, timeout_s=timeout_s if timeout_s is not None else _timeout_from_env()
    )


def _proto_type(kind: PluginType) -> int:
    from .grpc_proto import plugin_pb2

    return {
        PluginType.ADAPTER: plugin_pb2.ADAPTER,
        PluginType.AGENT: plugin_pb2.AGENT,
        PluginType.ACTION: plugin_pb2.ACTION,
        PluginType.DASHBOARD_COMPONENT: plugin_pb2.DASHBOARD_COMPONENT,
    }.get(kind, plugin_pb2.ADAPTER)


def _decode_result(response, method: str) -> dict:
    """TaskResponse / EventResponse → dict。失败在这里就变成这次调用的失败。"""
    if response.error:
        raise GrpcPluginError(f"{method}: {response.error}")
    if not response.success:
        raise GrpcPluginError(f"{method}: 远端报告失败但没有说明")
    if not response.result:
        return {}
    try:
        decoded = json.loads(response.result.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise GrpcPluginError(f"{method}: 远端返回的不是 JSON: {e}") from e
    return decoded if isinstance(decoded, dict) else {"result": decoded}


def parse_grpc_targets(raw: str | None = None) -> list[tuple[str, str]]:
    """解析 PLUGINS_GRPC="name=host:port,..."。"""
    raw = raw if raw is not None else os.environ.get("PLUGINS_GRPC", "")
    targets: list[tuple[str, str]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            logger.warning("Ignoring malformed PLUGINS_GRPC entry: %s", part)
            continue
        name, _, target = part.partition("=")
        targets.append((name.strip(), target.strip()))
    return targets


def register_grpc_plugins(
    parse=parse_grpc_targets, target_registry: PluginRegistry | None = None
) -> int:
    """接上 `PLUGINS_GRPC` 里点名、但插件目录里没有清单的远端插件,返回数量。

    常规形态不经过这里:清单里写 `endpoint` 的插件由发现流程直接建成代理
    (`PluginRegistry._activate`),和进程内插件走完全同一条路。这个函数只服务
    "临时接一个不在目录里的插件"——那种接法拿不到声明,也就没有任何能力,
    所以它接上的东西只用来确认"对面在不在"。
    """
    reg = target_registry or default_registry
    registered = 0
    for name, target in dict(parse() or []).items():
        if reg.manifest(name) is not None:
            continue  # 目录里有声明:发现流程已经按清单接上了
        manifest = Manifest(
            name=name,
            version="0.0.0",
            type=PluginType.ADAPTER,
            description=f"进程外插件({target});目录里没有清单,能力为空",
            class_name="",
            endpoint=target,
        )
        logger.warning(
            "PLUGINS_GRPC 里的 %s 在插件目录里没有清单:按空能力接上,它不会有任何能力"
            "被解析到。把 plugin.yaml(endpoint: %s)放进插件目录才是正道",
            name,
            target,
        )
        if _register_one(reg, manifest, target, _timeout_from_env()):
            registered += 1
    return registered


def _timeout_from_env() -> float:
    raw = os.environ.get("PLUGINS_GRPC_TIMEOUT_S", "")
    if not raw:
        return DEFAULT_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        logger.warning("PLUGINS_GRPC_TIMEOUT_S 不是数字(%r),用默认 %s", raw, DEFAULT_TIMEOUT_S)
        return DEFAULT_TIMEOUT_S
    return value if value > 0 else DEFAULT_TIMEOUT_S


def _register_one(
    reg: PluginRegistry, manifest: Manifest, target: str, timeout_s: float
) -> bool:
    proxy = GrpcPluginProxy(manifest, target, timeout_s=timeout_s)
    try:
        reg.register(manifest, proxy)
    except Exception as e:  # noqa: BLE001 - 一个远端接入失败不拖累其他
        logger.error("注册进程外插件 %s(%s)失败:%s", manifest.name, target, e)
        return False
    logger.info("gRPC plugin %s registered at %s", manifest.name, target)
    return True


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "GrpcPluginError",
    "GrpcPluginProxy",
    "make_proxy",
    "parse_grpc_targets",
    "register_grpc_plugins",
]
