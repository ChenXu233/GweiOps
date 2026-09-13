# engine/plugin_manager/grpc_loader.py
"""进程外 gRPC 插件加载器(骨架)。

目标形态(见 docs/plan/phase-b4-grpc.md):配置 `PLUGINS_GRPC="name=host:port,..."`
中的每个端点运行一个实现 proto PluginService 的插件进程,本加载器将其注册为
registry 内的 PluginBase 代理——handle_event/execute_task 经 gRPC 调用远端,
进程隔离与语言无关。

当前状态:**骨架**。生成 stub 需要 grpcio + grpcio-tools(尚未加入依赖),
`grpcio` 缺失或端点不可达时抛出 NotImplementedError/ConnectionError,
不影响进程内插件加载。stub 代码生成管线见子计划 A2。
"""

import logging
import os

from .base import PluginBase, PluginInfo

logger = logging.getLogger(__name__)


class GrpcPluginProxy(PluginBase):
    """远端 gRPC 插件的进程内代理。"""

    def __init__(self, name: str, target: str) -> None:
        self._name = name
        self._target = target
        self._stub = None

    def _ensure_stub(self):
        if self._stub is not None:
            return self._stub
        try:
            import grpc  # noqa: F401
        except ImportError as e:
            raise NotImplementedError(
                "gRPC 插件加载需要 grpcio/grpcio-tools 依赖(见 phase-b4 子计划)"
            ) from e
        raise NotImplementedError("stub 代码生成管线未实现(见 phase-b4 子计划 A2)")

    async def handle_event(self, event: str, data: dict) -> dict:
        stub = self._ensure_stub()
        raise NotImplementedError(f"gRPC dispatch to {self._target} pending: {stub}")

    async def execute_task(self, task: str, params: dict) -> dict:
        stub = self._ensure_stub()
        raise NotImplementedError(f"gRPC dispatch to {self._target} pending: {stub}")

    async def on_startup(self) -> None:
        logger.info("gRPC plugin %s proxy created for %s", self._name, self._target)

    async def on_shutdown(self) -> None:
        pass

    async def health_check(self) -> bool:
        try:
            self._ensure_stub()
            return True
        except Exception:
            return False


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


def register_grpc_plugins(parse=parse_grpc_targets) -> int:
    """将配置的远端插件注册进 registry(骨架:代理的生命周期方法可健康检查)。"""
    from .base import PluginType
    from .manifest import Manifest
    from .registry import registry

    registered = 0
    for name, target in parse():
        proxy = GrpcPluginProxy(name, target)
        manifest = Manifest(
            name=name,
            version="0.0.0",
            type=PluginType.ADAPTER,
            description=f"gRPC plugin at {target}",
            class_name="GrpcPluginProxy",
        )
        registry.register(manifest, proxy)
        registered += 1
    return registered
