# tests/test_integration/test_grpc_effect_provider.py
"""进程外插件当效果提供者:四方法与进程内提供者结果一致。

覆盖的是"变更单元不知道自己面对的是一个远端进程"这件事:
- execute 拿到句柄,undo 拿到同一句柄,window 读得出可撤性,verify 给出 ok + facts;
- 两种失败分得开:远端说得出"确定没碰到下游"记 failed(可重试),说不清记 unknown;
- 声明缺项时加载期就拒,不拖到执行期。

不 mock 传输层:这里起真的 gRPC 服务端。
"""

from __future__ import annotations

import asyncio
import json
from concurrent import futures

import pytest

grpc = pytest.importorskip("grpc")

from engine.change_unit import (
    VERDICT_FAILED,
    VERDICT_KEPT,
    VERDICT_ROLLED_BACK,
    VERDICT_UNKNOWN,
    ChangeUnit,
    Effect,
    JsonlLedger,
    Window,
    apply as apply_unit,
    rollback,
)
from engine.change_unit.errors import EffectNotApplied
from engine.plugin_manager.base import PluginType
from engine.plugin_manager.grpc_loader import GrpcPluginProxy
from engine.plugin_manager.grpc_proto import plugin_pb2_grpc
from engine.plugin_manager.grpc_server import build_servicer
from engine.plugin_manager.manifest import (
    EffectDecl,
    Manifest,
    ManifestError,
)
from engine.plugin_manager.registry import PluginRegistry


class RemoteEffectPlugin:
    """一个真的效果提供者:落一个文件,句柄就是文件名。"""

    def __init__(self, root) -> None:
        self.root = root
        self.calls: list[tuple[str, str, str]] = []
        self.fail_with: str = ""  # "" / "not_applied" / "unknown"

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event: str, data: dict) -> dict:
        return {"status": "ignored"}

    async def execute_task(self, task: str, params: dict) -> dict:
        # 四个方法都实现了,所以走不到这里;它在这里是为了证明"兜底还在"
        return {"task": task, "fallback": True}

    async def execute(self, task: str, args: dict) -> dict:
        self.calls.append(("execute", task, ""))
        if self.fail_with == "not_applied":
            raise EffectNotApplied("目标目录不存在")
        if self.fail_with == "unknown":
            raise RuntimeError("连接在半路断了")
        handle = f"{args.get('name', 'x')}.marker"
        (self.root / handle).write_text("done", encoding="utf-8")
        return {"handle": handle, "count": 1}

    async def undo(self, task: str, args: dict, handle: str) -> dict:
        self.calls.append(("undo", task, handle))
        target = self.root / handle
        removed = target.exists()
        target.unlink(missing_ok=True)
        return {"removed": removed}

    async def window(self, effect: Effect, handle: str | None) -> Window:
        self.calls.append(("window", effect.capability, handle or ""))
        return Window(unbounded=True, source="marker_present")

    async def verify(self, effect: Effect, handle: str) -> tuple[bool, dict]:
        self.calls.append(("verify", effect.capability, handle))
        return (self.root / handle).is_file(), {"marker": handle}


@pytest.fixture()
def remote(tmp_path):
    plugin = RemoteEffectPlugin(tmp_path)
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    plugin_pb2_grpc.add_PluginServiceServicer_to_server(build_servicer(plugin), server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    try:
        yield f"127.0.0.1:{port}", plugin
    finally:
        server.stop(0)


EFFECT_DECL = EffectDecl(
    capability="scan.todos",
    execute_task="scan_todos",
    undo_task="undo_scan_todos",
    undo_kind="symmetric",
    window_read="marker_present",
    verify=({"query": "marker_exists", "expect": "true"},),
    label="扫一遍并落印记",
    execute_args=("path", "name"),
)


def _manifest(**kw) -> Manifest:
    base = dict(
        name="remote-effect",
        version="1.0.0",
        type=PluginType.ACTION,
        description="进程外效果提供者",
        class_name="",
        binding="local",
        capabilities=["scan.todos"],
        tasks={"scan.todos": "scan_todos"},
        effects={"scan.todos": EFFECT_DECL},
    )
    base.update(kw)
    return Manifest(**base)


def _unit(tenant: str = "", binding: str = "local") -> ChangeUnit:
    """按清单里的声明造一个单元:效果引用来自 effects 块,不是手写的。"""
    decl = _manifest().effects["scan.todos"]
    return ChangeUnit(
        intent={"source": "test"},
        effect=decl.to_effect({"path": "x", "name": "u1"}),
        binding=binding,
        tenant=tenant,
    )


def _run(coro):
    return asyncio.run(coro)


def test_remote_provider_runs_a_whole_unit(remote, tmp_path):
    """执行、读窗口、验证、撤销:四项与进程内提供者同一套语义。"""
    target, plugin = remote
    proxy = GrpcPluginProxy(_manifest(), target)

    unit = _run(apply_unit(_unit(), proxy))
    assert unit.verdict == VERDICT_KEPT, unit.reason
    assert unit.handle == "u1.marker"
    assert (tmp_path / "u1.marker").is_file()
    # 窗口读到了:远端说"目标还在就能撤"
    assert unit.window is not None and unit.window.unbounded

    rolled = _run(rollback(unit, proxy))
    assert rolled.verdict == VERDICT_ROLLED_BACK, rolled.reason
    assert not (tmp_path / "u1.marker").exists()

    # 阶段确实按 phase 分开了,任务名取自清单
    assert ("execute", "scan_todos", "") in plugin.calls
    assert ("undo", "undo_scan_todos", "u1.marker") in plugin.calls
    assert ("verify", "scan.todos", "u1.marker") in plugin.calls


def test_remote_handle_is_opaque_and_survives_a_round_trip(remote, tmp_path):
    """句柄是不透明字符串:核心存进账本、原样带回来,从不解释它。"""
    target, _plugin = remote
    proxy = GrpcPluginProxy(_manifest(), target)
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")

    unit = _run(apply_unit(_unit(), proxy, ledger))
    row = _run(ledger.history(unit.id))[-1]
    assert row["handle"] == "u1.marker"

    # 从账本还原出来的单元还能接着撤
    restored = ChangeUnit.from_dict(row)
    assert restored.handle == "u1.marker"
    assert _run(rollback(restored, proxy)).verdict == VERDICT_ROLLED_BACK


def test_remote_says_not_applied_is_retryable(remote):
    """远端确定没碰到下游 → 单元记 failed(可照原样重试),不是 unknown。"""
    target, plugin = remote
    plugin.fail_with = "not_applied"
    unit = _run(apply_unit(_unit(), GrpcPluginProxy(_manifest(), target)))
    assert unit.verdict == VERDICT_FAILED, unit.reason
    assert "目标目录不存在" in unit.reason
    assert unit.facts["error"]["stage"] == "execute"


def test_remote_failure_without_a_verdict_stays_unknown(remote):
    """说不清的失败一律 unknown:请求可能已经到了对面,必须人去核。"""
    target, plugin = remote
    plugin.fail_with = "unknown"
    unit = _run(apply_unit(_unit(), GrpcPluginProxy(_manifest(), target)))
    assert unit.verdict == VERDICT_UNKNOWN, unit.reason
    assert "连接在半路断了" in unit.reason


def test_remote_verify_failure_rolls_back(remote, tmp_path):
    """验证不过就回滚,与进程内提供者一样——远端不享受豁免。"""
    target, plugin = remote
    proxy = GrpcPluginProxy(_manifest(), target)

    async def broken_verify(effect, handle):
        return False, {"why": "印记丢了"}

    plugin.verify = broken_verify  # type: ignore[assignment]
    unit = _run(apply_unit(_unit(), proxy))
    assert unit.verdict == VERDICT_ROLLED_BACK, unit.reason
    assert unit.facts["why"] == "印记丢了"


def test_remote_window_that_reports_nothing_blocks(remote):
    """远端报不出窗口 = 读不到:模式判不了可逆性,不许自动执行。"""
    target, plugin = remote

    async def no_window(effect, handle):
        return Window()

    plugin.window = no_window  # type: ignore[assignment]
    unit = _run(apply_unit(_unit(), GrpcPluginProxy(_manifest(), target)))
    from engine.change_unit import VERDICT_BLOCKED

    assert unit.verdict == VERDICT_BLOCKED, unit.reason
    assert "窗口" in unit.reason


def test_registry_resolves_remote_provider_by_binding(remote):
    """注册表按 (租户, 目标) 解析出远端提供者;效果声明照常由核心解释。"""
    target, _plugin = remote
    manifest = _manifest()
    reg = PluginRegistry()
    reg.register(manifest, GrpcPluginProxy(manifest, target))

    provider, decl = reg.effect_decl("scan.todos", tenant="", binding="local")
    assert isinstance(provider, GrpcPluginProxy)
    assert decl.execute_task == "scan_todos"
    # 绑错了目标就解析不到:跨环境执行是事故,不是配置错
    with pytest.raises(LookupError):
        reg.effect_decl("scan.todos", tenant="", binding="prod")


# ---------------------------------------------------------------------------
# 清单:坏声明在加载期就拒
# ---------------------------------------------------------------------------


def test_effect_missing_from_capabilities_is_rejected_at_register(remote):
    target, _plugin = remote
    manifest = _manifest(capabilities=["scan.read"])
    reg = PluginRegistry()
    with pytest.raises(ValueError, match="未列入 capabilities"):
        reg.register(manifest, GrpcPluginProxy(manifest, target))
    # 注册失败不留残影
    assert reg.names() == []


def test_remote_manifest_parses_effect_block(tmp_path):
    path = tmp_path / "plugin.yaml"
    path.write_text(
        "name: remote-effect\nversion: 1.0.0\ntype: action\ndescription: d\n"
        "endpoint: 127.0.0.1:50051\nbinding: local\n"
        "capabilities: [scan.todos]\n"
        "effects:\n"
        "  scan.todos:\n"
        "    execute: { task: scan_todos, args: [path] }\n"
        "    undo: { task: undo_scan_todos, kind: symmetric }\n"
        "    window: { read: marker_present }\n"
        "    verify:\n"
        "      - { query: marker_exists, expect: 'true' }\n",
        encoding="utf-8",
    )
    manifest = Manifest.from_yaml(path)
    decl = manifest.effects["scan.todos"]
    assert decl.undo_kind == "symmetric"
    assert decl.execute_args == ("path",)
    assert decl.window_read == "marker_present"


def test_broken_effect_block_is_rejected(tmp_path):
    path = tmp_path / "plugin.yaml"
    path.write_text(
        "name: remote-effect\nversion: 1.0.0\ntype: action\ndescription: d\n"
        "endpoint: 127.0.0.1:50051\ncapabilities: [scan.todos]\n"
        "effects:\n"
        "  scan.todos:\n"
        "    execute: { task: scan_todos }\n"
        "    window: { read: x }\n"
        "    verify: [{ query: q, expect: 'true' }]\n",
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="undo.task"):
        Manifest.from_yaml(path)


# ---------------------------------------------------------------------------
# 端到端:仓库自带示例插件真跑一遍效果四方法与配置下发
# ---------------------------------------------------------------------------


def test_demo_plugin_runs_an_effect_and_takes_its_config(tmp_path, monkeypatch):
    """一个只有清单和 endpoint 的插件,当一个真效果提供者用。

    这条钉的是"整条线通":清单的 effects / scopes 声明 → 发现 → 代理 → 四个 phase
    的 RPC → 插件的四个方法。中间任何一环错位,这里都会红。
    """
    import subprocess
    import sys
    from pathlib import Path

    from engine.change_unit import JsonlLedger, apply as apply_unit, rollback
    from engine.plugin_manager.grpc_loader import GrpcPluginProxy
    from engine.plugin_manager.registry import PluginRegistry

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
        plug = tmp_path / "demo-remote-scan"
        plug.mkdir()
        (plug / "plugin.yaml").write_text(
            (demo / "plugin.yaml")
            .read_text(encoding="utf-8")
            .replace("127.0.0.1:50055", f"127.0.0.1:{port}")
            .replace("default_enabled: false", "default_enabled: true"),
            encoding="utf-8",
        )
        work = tmp_path / "code"
        work.mkdir()
        (work / "x.py").write_text("# TODO: 修\nprint(1)\n", encoding="utf-8")

        monkeypatch.setenv("DEMO_REMOTE_SCAN_NOTE", "来自核心的配置")
        reg = PluginRegistry()
        assert reg.discover(builtin_dir=tmp_path) >= 1
        # 配置在启动之后推:launch 是"插件活了"与"它拿到配置了"的分界
        asyncio.run(reg.launch())

        provider, decl = reg.effect_decl("scan.todos", tenant="", binding="local")
        assert isinstance(provider, GrpcPluginProxy)

        unit = ChangeUnit(
            intent={"source": "test"},
            effect=decl.to_effect({"path": str(work)}),
            binding="local",
        )
        ledger = JsonlLedger(tmp_path / "ledger.jsonl")
        done = asyncio.run(apply_unit(unit, reg, ledger))
        assert done.verdict == VERDICT_KEPT, done.reason
        assert done.handle and (work / done.handle).is_file()
        assert done.facts.get("count") == 1

        # 配置真推下去了:印记里写着核心经 Configure 送来的值
        assert "来自核心的配置" in (work / done.handle).read_text(encoding="utf-8")

        back = asyncio.run(rollback(done, reg))
        assert back.verdict == VERDICT_ROLLED_BACK, back.reason
        assert not (work / done.handle).exists()
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
    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError(f"示例插件没在 {timeout_s} 秒内起来")
