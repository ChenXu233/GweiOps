# tests/test_integration/test_change_unit.py
"""变更单元:不变量用假 provider 验证;真 docker 的用例单独门控。"""

from __future__ import annotations

import asyncio
import importlib
import json
import shutil
import subprocess

import pytest

from engine.change_unit import (
    ChangeUnit,
    Effect,
    JsonlLedger,
    Window,
    apply,
    rollback,
    VERDICT_BLOCKED,
    VERDICT_IRREVERSIBLE,
    VERDICT_KEPT,
    VERDICT_ROLLED_BACK,
)

compose_mod = importlib.import_module("plugins.builtin.actions.docker-compose.plugin")


class FakeProvider:
    def __init__(
        self,
        *,
        pre: Window | None = None,
        post: Window | None = None,
        handle: str | None = "handle-1",
        verify_result: tuple[bool, dict] = (True, {"running": 2}),
        binding: str = "local",
    ) -> None:
        self.pre = pre or Window(unbounded=True, source="fake")
        self.post = post or Window(unbounded=True, source="fake")
        self.handle = handle
        self.verify_result = verify_result
        self.binding = binding
        self.executed = 0
        self.undone = 0

    async def window(self, effect, handle):
        return self.post if handle is not None else self.pre

    async def execute(self, task, args):
        self.executed += 1
        return {"handle": self.handle, "target": 2}

    async def undo(self, task, args, handle):
        self.undone += 1
        return {"restored": True}

    async def verify(self, effect, handle):
        return self.verify_result


def _unit(binding: str = "local") -> ChangeUnit:
    effect = Effect(task="scale", args={"service": "web"}, undo_task="undo_scale")
    return ChangeUnit(intent={"source": "test"}, effect=effect, binding=binding)


def test_blocked_when_window_unknown():
    provider = FakeProvider(pre=Window())
    unit = asyncio.run(apply(_unit(), provider))
    assert unit.verdict == VERDICT_BLOCKED
    assert provider.executed == 0


def test_kept_when_verified_and_ledger_records_binding(tmp_path):
    ledger = JsonlLedger(tmp_path / "units.jsonl")
    unit = asyncio.run(apply(_unit(), FakeProvider(), ledger))
    assert unit.verdict == VERDICT_KEPT
    assert unit.handle == "handle-1"
    rows = ledger.read()
    assert len(rows) == 1
    assert rows[0]["verdict"] == VERDICT_KEPT
    assert rows[0]["binding"] == "local"
    assert rows[0]["effect"]["undo_kind"] == "retained"


def test_post_window_shrinks_rolls_back():
    provider = FakeProvider(pre=Window(unbounded=True), post=Window(seconds=60))
    unit = asyncio.run(apply(_unit(), provider))
    assert unit.verdict == VERDICT_ROLLED_BACK
    assert provider.undone == 1


def test_verify_failure_rolls_back():
    provider = FakeProvider(verify_result=(False, {"running": 0}))
    unit = asyncio.run(apply(_unit(), provider))
    assert unit.verdict == VERDICT_ROLLED_BACK
    assert provider.undone == 1


def test_missing_handle_is_irreversible():
    provider = FakeProvider(handle=None)
    unit = asyncio.run(apply(_unit(), provider))
    assert unit.verdict == VERDICT_IRREVERSIBLE
    assert provider.undone == 0


def test_manual_rollback_requires_handle():
    with pytest.raises(ValueError):
        asyncio.run(rollback(_unit(), FakeProvider()))


def test_binding_mismatch_refused():
    provider = FakeProvider(binding="host-b")
    with pytest.raises(ValueError, match="binding 不匹配"):
        asyncio.run(apply(_unit("host-a"), provider))
    assert provider.executed == 0


def test_missing_binding_refused():
    with pytest.raises(ValueError, match="没有 binding"):
        asyncio.run(apply(_unit(""), FakeProvider()))


def test_illegal_undo_kind_rejected():
    with pytest.raises(ValueError):
        Effect(task="t", args={}, undo_task="u", undo_kind="magic")


def test_replay_uses_prior_result_without_second_effect(tmp_path):
    ledger = JsonlLedger(tmp_path / "units.jsonl")
    provider = FakeProvider()
    unit = _unit()
    unit.idempotency_key = "triage-42/comment/attempt-1"

    first = asyncio.run(apply(unit, provider, ledger))
    assert first.verdict == VERDICT_KEPT

    replay = _unit()
    replay.idempotency_key = "triage-42/comment/attempt-1"
    second = asyncio.run(apply(replay, provider, ledger))

    assert provider.executed == 1, "重放不得二次外呼"
    assert second.handle == first.handle
    assert second.verdict == VERDICT_KEPT
    assert second.reason.startswith("重放")
    assert len(ledger.read()) == 1


def test_idempotency_key_without_ledger_refused():
    unit = _unit()
    unit.idempotency_key = "k1"
    with pytest.raises(ValueError, match="没有账本"):
        asyncio.run(apply(unit, FakeProvider()))


def test_different_keys_execute_twice(tmp_path):
    ledger = JsonlLedger(tmp_path / "units.jsonl")
    provider = FakeProvider()
    a = _unit(); a.idempotency_key = "k-a"
    b = _unit(); b.idempotency_key = "k-b"
    asyncio.run(apply(a, provider, ledger))
    asyncio.run(apply(b, provider, ledger))
    assert provider.executed == 2
    assert len(ledger.read()) == 2


def _registry_for(provider: FakeProvider, capability: str = "fake.scale"):
    from engine.plugin_manager.base import PluginType
    from engine.plugin_manager.manifest import Manifest
    from engine.plugin_manager.registry import PluginRegistry

    reg = PluginRegistry()
    manifest = Manifest(
        name="fake-cap",
        version="1.0.0",
        type=PluginType.AGENT,
        description="fake",
        class_name="FakeProvider",
        capabilities=[capability],
        tasks={capability: "scale"},
    )
    reg.register(manifest, provider, key="fake@" + provider.tenant + "/" + provider.binding)
    return reg


def _unit_with_capability(tenant: str = "tenant-a", binding: str = "target-a") -> ChangeUnit:
    effect = Effect(
        task="scale", args={}, undo_task="undo_scale", capability="fake.scale"
    )
    return ChangeUnit(intent={}, effect=effect, tenant=tenant, binding=binding)


def test_apply_resolves_provider_from_registry():
    provider = FakeProvider()
    provider.tenant, provider.binding = "tenant-a", "target-a"
    unit = asyncio.run(apply(_unit_with_capability(), _registry_for(provider)))
    assert unit.verdict == VERDICT_KEPT
    assert provider.executed == 1


def test_registry_without_matching_target_raises():
    provider = FakeProvider()
    provider.tenant, provider.binding = "tenant-a", "target-a"
    reg = _registry_for(provider)
    with pytest.raises(LookupError, match="available"):
        asyncio.run(apply(_unit_with_capability(tenant="tenant-z", binding="target-z"), reg))


def test_apply_requires_capability_when_target_is_registry():
    provider = FakeProvider()
    provider.tenant, provider.binding = "tenant-a", "target-a"
    unit = _unit_with_capability()
    unit.effect = Effect(task="scale", args={}, undo_task="undo_scale")
    with pytest.raises(ValueError, match="没有 capability"):
        asyncio.run(apply(unit, _registry_for(provider)))


class FakeDocker:
    """记录命令并模拟 compose ps / up --scale 的状态。"""

    def __init__(self, replicas: int = 1, service: str = "web") -> None:
        self.replicas = replicas
        self.service = service
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], cwd: str) -> str:
        self.calls.append(list(args))
        if "ps" in args:
            return json.dumps(
                [{"Service": self.service, "State": "running"} for _ in range(self.replicas)]
            )
        if "up" in args:
            scale = args[args.index("--scale") + 1]
            self.replicas = int(scale.split("=")[1])
            return ""
        return ""


def _compose_effect(project_dir, service="web", replicas=2):
    """效果由声明构造;声明权在核心,插件只执行。"""
    return Effect(
        task="scale",
        args={"project_dir": str(project_dir), "service": service, "replicas": replicas},
        undo_task="undo_scale",
        undo_kind="symmetric",
        capability="compose.scale",
    )


def _compose_project(tmp_path):
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  web:\n    image: alpine:3.20\n", encoding="utf-8"
    )
    return tmp_path


def test_compose_scale_kept_and_undo_restores(tmp_path):
    project = _compose_project(tmp_path)
    docker = FakeDocker(replicas=1)
    plugin = compose_mod.DockerComposeAction(runner=docker)
    asyncio.run(plugin.on_startup())

    effect = _compose_effect(project, replicas=3)
    unit = asyncio.run(
        apply(ChangeUnit(intent={"issue": 1}, effect=effect, binding="local"), plugin)
    )

    assert unit.verdict == VERDICT_KEPT, unit.reason
    assert json.loads(unit.handle)["before"] == 1
    assert docker.replicas == 3

    asyncio.run(rollback(unit, plugin))
    assert docker.replicas == 1


def test_remote_binding_targets_other_daemon(tmp_path):
    project = _compose_project(tmp_path)
    docker = FakeDocker(replicas=2)
    plugin = compose_mod.DockerComposeAction(runner=docker, binding="ssh://ops@node-1")
    asyncio.run(plugin.on_startup())

    effect = _compose_effect(project, replicas=4)
    unit = asyncio.run(
        apply(ChangeUnit(intent={}, effect=effect, binding="ssh://ops@node-1"), plugin)
    )

    assert unit.verdict == VERDICT_KEPT, unit.reason
    assert docker.calls, "应当产生 docker 调用"
    assert docker.calls[0][:2] == ["-H", "ssh://ops@node-1"]
    assert all(call[:2] == ["-H", "ssh://ops@node-1"] for call in docker.calls)


def test_unit_cannot_run_on_another_host(tmp_path):
    project = _compose_project(tmp_path)
    plugin = compose_mod.DockerComposeAction(runner=FakeDocker(), binding="host-a")
    asyncio.run(plugin.on_startup())
    effect = _compose_effect(project, replicas=2)
    with pytest.raises(ValueError, match="binding 不匹配"):
        asyncio.run(apply(ChangeUnit(intent={}, effect=effect, binding="host-b"), plugin))


def test_compose_window_unknown_without_compose_file(tmp_path):
    plugin = compose_mod.DockerComposeAction(runner=FakeDocker())
    asyncio.run(plugin.on_startup())
    effect = _compose_effect(tmp_path, replicas=2)
    window = asyncio.run(plugin.window(effect, None))
    assert window.known is False
    unit = asyncio.run(apply(ChangeUnit(intent={}, effect=effect, binding="local"), plugin))
    assert unit.verdict == VERDICT_BLOCKED


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=15,
            check=True,
        )
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _docker_ready(), reason="docker daemon 未运行")
def test_real_compose_scale_roundtrip(tmp_path):
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  web:\n    image: alpine:3.20\n    command: sleep 300\n",
        encoding="utf-8",
    )
    plugin = compose_mod.DockerComposeAction()
    asyncio.run(plugin.on_startup())
    effect = _compose_effect(tmp_path, replicas=2)
    unit = asyncio.run(
        apply(ChangeUnit(intent={"issue": 1}, effect=effect, binding="local"), plugin)
    )
    try:
        assert unit.verdict == VERDICT_KEPT, unit.reason
    finally:
        if unit.handle:
            asyncio.run(plugin.undo("undo_scale", {}, unit.handle))
