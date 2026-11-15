# tests/test_integration/test_grpc_plugins.py
"""进程外 gRPC 插件:同一条注册路径、能力可解析、挂掉不拖垮核心。

这里起一个真的 gRPC 服务端(本机端口),不 mock 传输层——「能跑」这件事只有真连一次
才算数。测试覆盖:能力解析、任务名映射、Hook 回调、超时隔离、连不上时的行为。
"""

from __future__ import annotations

import asyncio
import json
import time
from concurrent import futures

import pytest

grpc = pytest.importorskip("grpc")

from engine.plugin_manager.base import PluginType
from engine.plugin_manager.grpc_loader import (
    GrpcPluginError,
    GrpcPluginProxy,
    parse_grpc_targets,
    register_grpc_plugins,
)
from engine.plugin_manager.grpc_proto import plugin_pb2, plugin_pb2_grpc
from engine.plugin_manager.manifest import Manifest
from engine.plugin_manager.registry import PluginRegistry


# ---------------------------------------------------------------------------
# 一个真的进程外插件:实现 proto PluginService
# ---------------------------------------------------------------------------


class DemoService(plugin_pb2_grpc.PluginServiceServicer):
    def __init__(self, *, hook_allowed: bool = True, delay_s: float = 0.0) -> None:
        self.hook_allowed = hook_allowed
        self.delay_s = delay_s
        self.calls: list[tuple[str, str]] = []
        self.hook_points: list[str] = []

    def Startup(self, request, context):
        self.calls.append(("Startup", request.plugin_info.name))
        return plugin_pb2.StartupResponse(success=True, message="ok")

    def Shutdown(self, request, context):
        self.calls.append(("Shutdown", ""))
        return plugin_pb2.ShutdownResponse(success=True)

    def HealthCheck(self, request, context):
        self.calls.append(("HealthCheck", ""))
        return plugin_pb2.HealthResponse(healthy=True, message="fine")

    def HandleEvent(self, request, context):
        self.calls.append(("HandleEvent", request.event))
        return plugin_pb2.EventResponse(
            success=True, result=json.dumps({"event": request.event}).encode()
        )

    def ExecuteTask(self, request, context):
        if self.delay_s:
            import time

            time.sleep(self.delay_s)
        self.calls.append(("ExecuteTask", request.task))
        params = json.loads(request.params.decode()) if request.params else {}
        return plugin_pb2.TaskResponse(
            success=True,
            result=json.dumps({"task": request.task, "echo": params}).encode(),
        )

    def HandleHook(self, request, context):
        self.hook_points.append(request.point)
        if not self.hook_allowed:
            return plugin_pb2.HookResponse(allowed=False, error="")
        payload = json.loads(request.payload.decode()) if request.payload else {}
        payload["seen"] = True
        return plugin_pb2.HookResponse(allowed=True, payload=json.dumps(payload).encode())


@pytest.fixture()
def remote_plugin():
    """真起一个 gRPC 服务端,监听本机随机端口。"""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    service = DemoService()
    plugin_pb2_grpc.add_PluginServiceServicer_to_server(service, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    try:
        yield f"127.0.0.1:{port}", service
    finally:
        server.stop(0)


def _manifest(**kw) -> Manifest:
    base = dict(
        name="remote-scan",
        version="1.2.0",
        type=PluginType.AGENT,
        description="进程外扫描插件",
        class_name="",
        capabilities=["scan.dependencies"],
        tasks={"scan.dependencies": "scan"},
    )
    base.update(kw)
    return Manifest(**base)


# ---------------------------------------------------------------------------
# 清单:声明在清单里,不上 wire
# ---------------------------------------------------------------------------


def test_remote_manifest_requires_endpoint_instead_of_class_name(tmp_path):
    from engine.plugin_manager.manifest import Manifest as M, ManifestError

    ok = tmp_path / "remote.yaml"
    ok.write_text(
        "name: remote\nversion: 1.0.0\ntype: agent\ndescription: d\n"
        "endpoint: 127.0.0.1:50051\ncapabilities: [scan.dependencies]\n",
        encoding="utf-8",
    )
    manifest = M.from_yaml(ok)
    assert manifest.endpoint == "127.0.0.1:50051"
    assert manifest.class_name == ""

    neither = tmp_path / "neither.yaml"
    neither.write_text(
        "name: remote\nversion: 1.0.0\ntype: agent\ndescription: d\n", encoding="utf-8"
    )
    with pytest.raises(ManifestError) as exc:
        M.from_yaml(neither)
    assert "class_name" in str(exc.value) and "endpoint" in str(exc.value)

    both = tmp_path / "both.yaml"
    both.write_text(
        "name: remote\nversion: 1.0.0\ntype: agent\ndescription: d\n"
        "class_name: X\nendpoint: 127.0.0.1:50051\n",
        encoding="utf-8",
    )
    with pytest.raises(ManifestError) as exc:
        M.from_yaml(both)
    assert "只能给一个" in str(exc.value)


def test_remote_manifest_keeps_declarations():
    """effects / hooks / schedules 留在清单里:进程没连上时控制台也要能讲清它是什么。"""
    manifest = _manifest(
        binding="prod", tenant="acme", capabilities=["scan.dependencies", "scan.read"]
    )
    assert manifest.binding == "prod"
    assert manifest.tenant == "acme"


# ---------------------------------------------------------------------------
# 代理:一次真调用
# ---------------------------------------------------------------------------


def test_proxy_executes_task_over_the_wire(remote_plugin):
    target, service = remote_plugin

    async def run():
        proxy = GrpcPluginProxy(_manifest(), target)
        try:
            await proxy.on_startup()
            assert await proxy.health_check() is True
            result = await proxy.execute_task("scan", {"repo": "acme/api"})
            event = await proxy.handle_event("scan.requested", {"repo": "acme/api"})
            return result, event
        finally:
            await proxy.on_shutdown()

    result, event = asyncio.run(run())
    assert result == {"task": "scan", "echo": {"repo": "acme/api"}}
    assert event == {"event": "scan.requested"}
    assert ("ExecuteTask", "scan") in service.calls


def test_proxy_hook_round_trip_and_veto(remote_plugin):
    target, service = remote_plugin

    async def run(allowed: bool):
        service.hook_allowed = allowed
        proxy = GrpcPluginProxy(_manifest(), target)
        return await proxy.handle_hook("comment.posting", {"body": "hi"})

    transformed = asyncio.run(run(True))
    assert transformed == {"body": "hi", "seen": True}

    vetoed = asyncio.run(run(False))
    assert vetoed is False  # 远端说不许,核心据此短路
    assert service.hook_points == ["comment.posting", "comment.posting"]


def test_proxy_wraps_connection_failure():
    """连不上时抛本插件自己的错,不是裸 grpc 异常。"""

    async def run():
        proxy = GrpcPluginProxy(_manifest(), "127.0.0.1:1")  # 没人监听
        return await proxy.execute_task("scan", {})

    with pytest.raises(GrpcPluginError):
        asyncio.run(run())


def test_proxy_timeout_isolated(remote_plugin):
    """远端慢到超时:这次调用失败,但不挂住核心。"""
    target, service = remote_plugin
    service.delay_s = 1.0

    async def run():
        proxy = GrpcPluginProxy(_manifest(), target, timeout_s=0.2)
        started = time.monotonic()
        with pytest.raises(GrpcPluginError):
            await proxy.execute_task("scan", {})
        return time.monotonic() - started

    elapsed = asyncio.run(run())
    # 远端要 1 秒,核心 0.2 秒就该放手
    assert elapsed < 0.9, f"超时没有生效,等了 {elapsed:.2f}s"


# ---------------------------------------------------------------------------
# 注册:与进程内插件同一条路径
# ---------------------------------------------------------------------------


def test_registered_remote_plugin_resolves_capability(remote_plugin, monkeypatch):
    target, _ = remote_plugin
    monkeypatch.setenv("PLUGINS_GRPC", f"remote-scan={target}")

    reg = PluginRegistry()
    reg.register(_manifest(endpoint=target), GrpcPluginProxy(_manifest(endpoint=target), target))

    provider = reg.best_capability_provider("scan.dependencies")
    assert provider is not None
    assert isinstance(provider, GrpcPluginProxy)
    # 清单里的 tasks 映射照常生效:能力名到任务名的翻译在核心
    assert asyncio.run(reg.run_capability("scan.dependencies", {})) == {
        "task": "scan",
        "echo": {},
    }


def test_discovery_builds_proxy_for_manifest_with_endpoint(tmp_path, monkeypatch):
    """清单写 endpoint 就够:发现流程自己建代理,不导入任何代码。"""
    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    plug = tmp_path / "remote-scan"
    plug.mkdir()
    (plug / "plugin.yaml").write_text(
        "name: remote-scan\nversion: 1.2.0\ntype: agent\ndescription: 进程外扫描\n"
        "endpoint: 127.0.0.1:50051\nbinding: prod\n"
        "capabilities: [scan.dependencies]\ntasks:\n  scan.dependencies: scan\n",
        encoding="utf-8",
    )
    reg = PluginRegistry()
    assert reg.discover(builtin_dir=tmp_path) == 1

    provider = reg.best_capability_provider("scan.dependencies")
    assert isinstance(provider, GrpcPluginProxy)
    # 清单里声明的 binding 被抄到实例属性上,按目标的解析才找得到它
    assert provider.binding == "prod"
    assert reg.manifest("remote-scan").endpoint == "127.0.0.1:50051"
    assert reg.resolve("scan.dependencies", tenant="", binding="prod") is provider


def test_discovery_skips_remote_plugin_not_enabled(tmp_path, monkeypatch):
    """进程外插件同样遵守"发现 ≠ 启用"。"""
    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    plug = tmp_path / "remote-scan"
    plug.mkdir()
    (plug / "plugin.yaml").write_text(
        "name: remote-scan\nversion: 1.2.0\ntype: agent\ndescription: d\n"
        "endpoint: 127.0.0.1:50051\ndefault_enabled: false\n"
        "capabilities: [scan.dependencies]\n",
        encoding="utf-8",
    )
    reg = PluginRegistry()
    assert reg.discover(builtin_dir=tmp_path) == 0
    # 但它在"发现到"的名单里,控制台因此能把它打开
    assert [m.name for m in reg.available()] == ["remote-scan"]
    assert reg.best_capability_provider("scan.dependencies") is None


def test_enable_remote_plugin_at_runtime(tmp_path, monkeypatch):
    """运行期打开一个未启用的进程外插件:建代理、进索引。"""
    monkeypatch.delenv("PLUGINS_ENABLED", raising=False)
    monkeypatch.delenv("PLUGINS_DISABLED", raising=False)
    plug = tmp_path / "remote-scan"
    plug.mkdir()
    (plug / "plugin.yaml").write_text(
        "name: remote-scan\nversion: 1.2.0\ntype: agent\ndescription: d\n"
        "endpoint: 127.0.0.1:50051\ndefault_enabled: false\n"
        "capabilities: [scan.dependencies]\n",
        encoding="utf-8",
    )
    reg = PluginRegistry()
    reg.discover(builtin_dir=tmp_path)

    asyncio.run(reg.enable("remote-scan"))
    assert isinstance(reg.best_capability_provider("scan.dependencies"), GrpcPluginProxy)
    asyncio.run(reg.disable("remote-scan"))
    assert reg.best_capability_provider("scan.dependencies") is None


def test_parse_grpc_targets_ignores_malformed():
    assert parse_grpc_targets("a=1.2.3.4:5, broken ,b=6.7.8.9:10") == [
        ("a", "1.2.3.4:5"),
        ("b", "6.7.8.9:10"),
    ]


def test_register_grpc_plugins_only_takes_unlisted_names():
    """PLUGINS_GRPC 只兜底"目录里没有清单"的临时接入,不覆盖已有声明。"""
    reg = PluginRegistry()
    reg.register(_manifest(), GrpcPluginProxy(_manifest(), "127.0.0.1:9"))
    count = register_grpc_plugins(
        parse=lambda: [
            ("remote-scan", "127.0.0.1:9"),   # 已有清单:跳过
            ("adhoc", "127.0.0.1:10"),        # 没清单:按空能力接上
        ],
        target_registry=reg,
    )
    assert count == 1
    # 已有声明的能力还在,地址没被环境变量换掉
    provider = reg.best_capability_provider("scan.dependencies")
    assert isinstance(provider, GrpcPluginProxy)
    assert provider._target == "127.0.0.1:9"
    # 临时接入的那个确实在,但没有任何能力
    assert reg.get("adhoc") is not None


# ---------------------------------------------------------------------------
# 端到端:仓库里那个示例插件真跑一遍
# ---------------------------------------------------------------------------


def test_demo_plugin_end_to_end(tmp_path):
    """起仓库自带的示例服务端,让注册表发现它的清单、调它的能力。

    这条钉的是"整条线通":清单 → 发现 → 代理 → RPC → 业务实现。中间任何一环
    错位(任务名对不上、编解码不一致、清单没被认成进程外),这里都会红。
    """
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    demo = root / "deploy" / "grpc-plugin-demo"

    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, str(demo / "server.py"), "--port", str(port)],
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_port(port)
        # 清单拷进临时插件根,endpoint 换成这次起的端口
        plug = tmp_path / "demo-remote-scan"
        plug.mkdir()
        (plug / "plugin.yaml").write_text(
            (demo / "plugin.yaml")
            .read_text(encoding="utf-8")
            .replace("127.0.0.1:50055", f"127.0.0.1:{port}")
            .replace("default_enabled: false", "default_enabled: true"),
            encoding="utf-8",
        )
        # 待办标记:让扫描有东西可数
        (tmp_path / "code").mkdir()
        (tmp_path / "code" / "x.py").write_text("# TODO: 修\nprint(1)\n", encoding="utf-8")

        reg = PluginRegistry()
        assert reg.discover(builtin_dir=tmp_path) == 1
        result = asyncio.run(
            reg.run_capability("scan.todos", {"path": str(tmp_path / "code")})
        )
        assert result["status"] == "ok"
        assert result["count"] == 1
        assert result["hits"][0]["path"] == "x.py"
    finally:
        proc.terminate()
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port(port: int, timeout_s: float = 15.0) -> None:
    import socket

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError(f"示例插件没在 {timeout_s} 秒内起来")
