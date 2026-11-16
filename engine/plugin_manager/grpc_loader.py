# engine/plugin_manager/grpc_loader.py
"""进程外 gRPC 插件 —— 插件跑在自己的进程里,核心只持有一个代理。

形态:`plugin.yaml` 里写 `endpoint: host:port`(代替 `class_name`)。声明在清单里
(能力、效果、Hook 订阅、周期),wire 只承载调用——两边因此走同一条注册路径,控制台
在对面进程没起来时也能把它讲清楚。

地址可以用环境变量覆盖,一份清单就能服务多个环境:

    PLUGINS_GRPC="scan-agent=10.0.0.5:50051,other=127.0.0.1:50052"

覆盖规则是「清单声明 endpoint」优先于「环境变量里同名条目」的默认地址;环境变量里
列出的名字即使清单没声明,也按最小清单(一个能力都没有的适配器)接上,便于临时接入。

效果(execute / undo / window / verify)也走这条代理:进程内提供者实现四个方法,
远端只实现 `execute_task`,四个阶段靠 `metadata["phase"]` 区分。两边对核心的输出
形状一致——单元不知道自己在跟一个远端进程说话。

**句柄是不透明字符串**,与进程内插件同一条规则:远端在 execute 的返回值里给
`handle`,核心原样存进账本、再原样带回来。核心从不解释它,所以远端可以把它当
自增 id、文件名或签过名的令牌用。

失败隔离的边界在这里:

- 对面连不上、超时、抛错,**只影响本插件**——异常在代理内被翻译成本插件的失败,
  不往调用方的工作流里扔裸 grpc 异常;
- 核心侧每次调用都有超时(`PLUGINS_GRPC_TIMEOUT_S`,默认 10 秒),一个卡住的远端
  进程不会把整条工作流挂在那里。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import TYPE_CHECKING, Any

from .base import PluginBase, PluginType
from .manifest import Manifest
from .registry import PluginRegistry, registry as default_registry

if TYPE_CHECKING:  # 只为注解:运行期不导入,免得插件管理器依赖变更单元
    from engine.change_unit.model import Effect, Window

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 10.0

# TaskResponse.error_kind 的取值:远端确定没碰到下游。核心据此把单元记成 failed
# (可以照原样重试),而不是 unknown(要人去核)。
NOT_APPLIED = "not_applied"


class GrpcPluginError(RuntimeError):
    """远端插件调用失败。"""


class GrpcPluginProxy(PluginBase):
    """远端 gRPC 插件的进程内代理:把每一次调用翻成一次 RPC。

    清单里声明的能力名、任务名映射、Hook 订阅都由核心解释,代理不认识它们。
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
        # 实例属性照抄清单声明,核心按它们解析 (租户, 目标)
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
        """跑一次 RPC,把 grpc 的异常翻译成本插件的失败(GrpcPluginError)。"""
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
        """握手:告诉远端它是谁、要哪些配置,顺带核一遍健康状态。

        连不上只记日志,下一次调用还能成;真的不能用时 `health_check()` 会说 false。
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
            except Exception:  # noqa: BLE001 - 关不掉只记日志
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

    # -- 效果四方法:与进程内提供者同名同语义 -------------------------

    async def _phase(self, phase: str, task: str, params: dict, method: str) -> dict:
        """跑一个效果阶段。与能力调用同为 ExecuteTask,靠 metadata 里的 phase 区分。

        阶段声明的解释权在核心(清单里的 effects 块),远端只需要知道"当前阶段该干
        什么"——它不认识效果名,也不该认识。
        """
        from .grpc_proto import plugin_pb2

        payload = json.dumps(params, ensure_ascii=False, default=str).encode("utf-8")
        response = await self._call(
            "ExecuteTask",
            plugin_pb2.TaskRequest(
                task=task, params=payload, metadata={"phase": phase}
            ),
        )
        return _decode_result(response, f"{method}({phase})")

    async def execute(self, task: str, args: dict) -> dict:
        return await self._phase("execute", task, args, "execute")

    async def undo(self, task: str, args: dict, handle: str) -> dict:
        # 撤销拿到的既有参数也有句柄:参数说明这是哪个对象,句柄说明是哪一次改动。
        return await self._phase(
            "undo", task, {"args": dict(args), "handle": handle}, "undo"
        )

    async def window(self, effect, handle: str | None) -> "Window":
        raw = await self._phase(
            "window",
            effect.capability,
            {"effect": _effect_payload(effect), "handle": handle},
            "window",
        )
        return _window_from(raw)

    async def verify(self, effect, handle: str) -> tuple[bool, dict]:
        raw = await self._phase(
            "verify",
            effect.capability,
            {"effect": _effect_payload(effect), "handle": handle},
            "verify",
        )
        facts = raw.get("facts") if isinstance(raw.get("facts"), dict) else {}
        return bool(raw.get("ok")), dict(facts)

    # -- 配置 -------------------------------------------------------

    async def configure(self, scope: str, values: dict, missing: list[str]) -> None:
        """把核心的配置值交给远端插件进程。

        远端的 `config.get_scope_config()` 读不到核心的环境变量与库,所以值只能
        从这条 RPC 过来。粗粒度、全量、一 scope 一次:远端不需要知道值是怎么来的。
        """
        from .grpc_proto import plugin_pb2

        response = await self._call(
            "Configure",
            plugin_pb2.ConfigureRequest(
                scope=scope,
                config={str(k): str(v) for k, v in values.items()},
                missing=list(missing or []),
            ),
        )
        if not response.success:
            # 插件拒收(它自己校验不过):说出来,但单次推送失败不拦住其它 scope
            raise GrpcPluginError(
                f"{self._name}.configure({scope}) 被拒:{response.message or '(没有说明)'}"
            )

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
    """发现期建代理。超时取自环境(`PLUGINS_GRPC_TIMEOUT_S`)。"""
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


def _effect_payload(effect) -> dict:
    """效果在 wire 上的样子。与 `engine.change_unit.Effect` 同形,远端读得出参数与验证规则。"""
    return {
        "task": effect.task,
        "args": dict(effect.args),
        "undo_task": effect.undo_task,
        "undo_kind": effect.undo_kind,
        "label": effect.label,
        "capability": effect.capability,
        "verify": [dict(rule) for rule in effect.verify],
    }


def _window_from(raw: dict) -> "Window":
    """window 阶段的返回值 → Window。

    只有远端知道"还能撤多久",所以这里不替它猜:报不出 seconds 也不报 unbounded
    就是 unknown,单元按不可逆处理。
    """
    from engine.change_unit.model import Window

    seconds = raw.get("seconds")
    return Window(
        seconds=seconds if isinstance(seconds, int) and not isinstance(seconds, bool) else None,
        unbounded=bool(raw.get("unbounded")),
        source=str(raw.get("source") or ""),
        estimated=bool(raw.get("estimated")),
    )


def _decode_result(response, method: str) -> dict:
    """TaskResponse / EventResponse → dict,失败在这里变成这次调用的失败。

    远端说得出"确定没碰到下游"(`error_kind == "not_applied"`)时,翻成
    `EffectNotApplied`(可照原样重试);说不清就保持 `GrpcPluginError`,单元据此记 unknown。
    """
    if response.error or not response.success:
        message = response.error or "远端报告失败但没有说明"
        if getattr(response, "error_kind", "") == NOT_APPLIED:
            from engine.change_unit.errors import EffectNotApplied

            raise EffectNotApplied(f"{method}: {message}")
        raise GrpcPluginError(f"{method}: {message}")
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
    """接上 `PLUGINS_GRPC` 里点名、插件目录里没有清单的远端插件,返回数量。

    常规形态不经过这里:清单里写 `endpoint` 的插件由发现流程直接建成代理
    (`PluginRegistry._activate`),和进程内插件走完全同一条路。本函数只服务
    "临时接一个不在插件目录里的远端插件"——该接法拿不到清单声明,也就没有任何能力,
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
    "NOT_APPLIED",
    "GrpcPluginError",
    "GrpcPluginProxy",
    "make_proxy",
    "parse_grpc_targets",
    "register_grpc_plugins",
]
