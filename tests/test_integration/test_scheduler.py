# tests/test_integration/test_scheduler.py
"""周期巡检:清单里的周期怎么校验、怎么换算、怎么装进调度器。

这一组都不需要 DBOS 与 Postgres:调度器的写入点由调用方注入,`apply_registry_schedules`
因此可以在没有系统库的情况下被检查"装了哪些、漏了哪些、删了哪些"。
"""

import textwrap
from pathlib import Path

import pytest

from engine.plugin_manager.base import PluginType
from engine.plugin_manager.manifest import Manifest, ManifestError, ScheduleDecl
from engine.scheduler import (
    SCHEDULE_PREFIX,
    apply_registry_schedules,
    every_to_cron,
    schedule_inputs,
    schedule_name,
)
from engine.shared.metrics import metrics
from engine.workflows.scan import signal_from_scan


MANIFEST = """
name: {name}
version: 1.0.0
type: agent
description: test
class_name: Whatever
capabilities: [scan.deps]
triggers:
  - type: schedule
    every: {every}
    capability: {capability}
"""


def write_manifest(tmp_path: Path, *, name="scan-plugin", every="6h", capability="scan.deps") -> Path:
    path = tmp_path / "plugin.yaml"
    path.write_text(
        textwrap.dedent(MANIFEST).format(name=name, every=every, capability=capability),
        encoding="utf-8",
    )
    return path


def make_manifest(name: str, *schedules: ScheduleDecl) -> Manifest:
    return Manifest(
        name=name,
        version="1.0.0",
        type=PluginType.AGENT,
        description="test",
        class_name="Whatever",
        capabilities=[s.capability for s in schedules],
        schedules=schedules,
    )


class FakeRegistry:
    def __init__(self, *manifests: Manifest) -> None:
        self._manifests = list(manifests)

    def manifests(self) -> list[Manifest]:
        return self._manifests


# ---------------------------------------------------------------------------
# 周期 → cron
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "cron"),
    [
        (30, "*/30 * * * * *"),
        (300, "0 */5 * * * *"),
        (1800, "0 */30 * * * *"),
        (21600, "0 0 */6 * * *"),
        (43200, "0 0 */12 * * *"),
        (86400, "0 0 0 * * *"),
    ],
)
def test_every_to_cron(seconds: int, cron: str):
    assert every_to_cron(seconds) == cron


# ---------------------------------------------------------------------------
# 清单校验
# ---------------------------------------------------------------------------


def test_schedule_is_parsed_into_seconds(tmp_path: Path):
    manifest = Manifest.from_yaml(write_manifest(tmp_path, every="6h"))
    assert manifest.schedules == (ScheduleDecl(capability="scan.deps", every_s=21600),)


def test_schedule_accepts_plain_seconds(tmp_path: Path):
    manifest = Manifest.from_yaml(write_manifest(tmp_path, every=1800))
    assert manifest.schedules[0].every_s == 1800


def test_trigger_without_schedule_type_is_left_alone(tmp_path: Path):
    path = tmp_path / "plugin.yaml"
    path.write_text(
        textwrap.dedent(
            """
            name: event-only
            version: 1.0.0
            type: agent
            description: test
            class_name: Whatever
            triggers:
              - type: event
                events: [issue.created]
            """
        ),
        encoding="utf-8",
    )
    assert Manifest.from_yaml(path).schedules == ()


@pytest.mark.parametrize(
    ("every", "reason"),
    [
        ("45m", "不整除"),
        ("7h", "不整除"),
        ("90s", "不整除"),
        ("0", "大于 0"),
        ("abc", "读不出"),
    ],
)
def test_bad_every_is_rejected_at_load(tmp_path: Path, every: str, reason: str):
    with pytest.raises(ManifestError) as exc:
        Manifest.from_yaml(write_manifest(tmp_path, every=every))
    assert reason in str(exc.value)


def test_capability_must_be_declared(tmp_path: Path):
    with pytest.raises(ManifestError) as exc:
        Manifest.from_yaml(write_manifest(tmp_path, capability="scan.other"))
    assert "capabilities" in str(exc.value)


def test_missing_capability_is_rejected(tmp_path: Path):
    with pytest.raises(ManifestError):
        Manifest.from_yaml(write_manifest(tmp_path, capability=""))


def test_bad_schedule_never_reaches_the_registry(tmp_path: Path):
    """坏周期不是"装上但跑不对":它在发现阶段就被挡下,并计一次发现错误。"""
    from engine.plugin_manager.registry import PluginRegistry

    root = tmp_path / "plugins"
    pkg = root / "badscan"
    pkg.mkdir(parents=True)
    (pkg / "plugin.py").write_text("", encoding="utf-8")
    (pkg / "plugin.yaml").write_text(
        textwrap.dedent(MANIFEST).format(name="badscan", every="45m", capability="scan.deps"),
        encoding="utf-8",
    )

    before = metrics.sum_metric("plugin_discovery_errors_total")
    registry = PluginRegistry()
    loaded = registry.discover(builtin_dir=tmp_path / "nothing", extra_dirs=[str(root)])

    assert loaded == 0
    assert registry.manifests() == []
    assert metrics.sum_metric("plugin_discovery_errors_total") > before


# ---------------------------------------------------------------------------
# 装进调度器
# ---------------------------------------------------------------------------


def test_schedule_inputs_carry_name_cron_and_context():
    registry = FakeRegistry(
        make_manifest("alpha", ScheduleDecl(capability="scan.deps", every_s=21600)),
        make_manifest("beta", ScheduleDecl(capability="scan.certs", every_s=86400)),
    )

    entries = schedule_inputs(registry, tenant="acme")

    assert [e["schedule_name"] for e in entries] == [
        schedule_name("alpha", "scan.deps"),
        schedule_name("beta", "scan.certs"),
    ]
    assert [e["schedule"] for e in entries] == ["0 0 */6 * * *", "0 0 0 * * *"]
    assert entries[0]["context"] == {
        "tenant_slug": "acme",
        "capability": "scan.deps",
        "plugin": "alpha",
        "schedule_name": schedule_name("alpha", "scan.deps"),
        "every_s": 21600,
    }


def test_apply_reports_failures_without_blocking_the_rest():
    registry = FakeRegistry(
        make_manifest("good", ScheduleDecl(capability="scan.deps", every_s=3600)),
        make_manifest("bad", ScheduleDecl(capability="scan.certs", every_s=7200)),
    )
    installed: list[str] = []

    def apply(entries):
        name = entries[0]["schedule_name"]
        if "bad" in name:
            raise RuntimeError("cron 写坏了")
        installed.append(name)

    outcome = apply_registry_schedules(
        registry, apply=apply, list_schedules=lambda: [], delete=lambda name: None
    )

    assert installed == [schedule_name("good", "scan.deps")]
    assert outcome["applied"] == installed
    assert [f["schedule"] for f in outcome["failed"]] == [schedule_name("bad", "scan.certs")]
    assert "cron 写坏了" in outcome["failed"][0]["error"]


def test_apply_removes_schedules_nobody_declares_anymore():
    registry = FakeRegistry(
        make_manifest("kept", ScheduleDecl(capability="scan.deps", every_s=3600))
    )
    removed: list[str] = []

    outcome = apply_registry_schedules(
        registry,
        apply=lambda entries: None,
        list_schedules=lambda: [
            {"schedule_name": schedule_name("kept", "scan.deps")},
            {"schedule_name": schedule_name("gone", "scan.certs")},
            {"schedule_name": "someone-elses-job"},
        ],
        delete=removed.append,
    )

    assert removed == [schedule_name("gone", "scan.certs")]
    assert outcome["removed"] == removed


def test_schedule_names_carry_the_platform_prefix():
    assert schedule_name("p", "scan.deps").startswith(SCHEDULE_PREFIX)


# ---------------------------------------------------------------------------
# 巡检结果 → 信号
# ---------------------------------------------------------------------------


def test_empty_scan_is_not_an_incident():
    assert signal_from_scan(None, capability="scan.deps") is None
    assert signal_from_scan({}, capability="scan.deps") is None


def test_scan_result_becomes_a_signal():
    signal = signal_from_scan(
        {
            "subject": "acme/api",
            "title": "3 个依赖有安全公告",
            "detail": "httpx, requests, urllib3",
            "severity": "medium",
            "ref": "deps:acme/api",
            "count": 3,
        },
        capability="scan.deps",
    )

    assert signal["source"] == "scan"
    assert signal["subject"] == "acme/api"
    assert signal["ref"] == "deps:acme/api"
    assert signal["capability"] == "scan.deps"
    assert signal["count"] == 3


@pytest.mark.parametrize("raw", ["not-a-dict", 42, ["a"]])
def test_scan_result_with_wrong_shape_is_a_bug(raw):
    with pytest.raises(ValueError):
        signal_from_scan(raw, capability="scan.deps")


@pytest.mark.parametrize("raw", [{"title": "只有标题"}, {"subject": "只有主体"}])
def test_scan_result_missing_subject_or_title_is_a_bug(raw):
    with pytest.raises(ValueError):
        signal_from_scan(raw, capability="scan.deps")
