# tests/test_integration/test_selfcheck.py
"""平台自检:只报真问题。

它挂在周期巡检上(scan 把非 None 的结果包成信号),所以这里只测"什么算问题"。
"""

from __future__ import annotations

import asyncio
from collections import namedtuple

import pytest

from plugins.builtin.agents.selfcheck import plugin as sc

Usage = namedtuple("usage", "total used free")
GB = 1_000_000_000


def _disk(free_ratio: float):
    total = 100 * GB
    free = int(total * free_ratio)
    return Usage(total=total, used=total - free, free=free)


def test_a_healthy_workspace_says_nothing(monkeypatch):
    monkeypatch.setattr(sc.shutil, "disk_usage", lambda path: _disk(0.5))
    assert sc.disk_finding() is None


def test_a_full_workspace_is_a_high_severity_finding(monkeypatch):
    monkeypatch.setattr(sc.shutil, "disk_usage", lambda path: _disk(0.03))
    finding = sc.disk_finding()
    assert finding is not None
    assert finding["ref"] == "selfcheck:disk"
    assert finding["severity"] == "high"
    assert finding["subject"] == "gwei-engine"
    assert "3%" in finding["detail"]


def test_no_workspace_directory_means_no_disk_check(monkeypatch):
    def boom(path):
        raise OSError("nope")

    monkeypatch.setattr(sc.shutil, "disk_usage", boom)
    assert sc.disk_finding() is None


def _queued(n: int):
    async def fake(queue_name: str, limit: int):
        return [{"id": f"w{i}"} for i in range(n)]

    return fake


def test_a_short_queue_says_nothing(monkeypatch):
    monkeypatch.setattr(sc.DBOS, "list_queued_workflows_async", _queued(3))
    assert asyncio.run(sc.queue_finding()) is None


def test_a_backlogged_queue_is_reported(monkeypatch):
    monkeypatch.setattr(sc.DBOS, "list_queued_workflows_async", _queued(sc.QUEUE_WARN + 1))
    finding = asyncio.run(sc.queue_finding())
    assert finding is not None
    assert finding["ref"] == "selfcheck:queue"
    assert finding["severity"] == "medium"


def test_an_unreadable_queue_is_not_a_finding(monkeypatch):
    async def boom(queue_name: str, limit: int):
        raise RuntimeError("dbos 没起来")

    monkeypatch.setattr(sc.DBOS, "list_queued_workflows_async", boom)
    assert asyncio.run(sc.queue_finding()) is None


def test_first_problem_wins(monkeypatch):
    monkeypatch.setattr(sc.shutil, "disk_usage", lambda path: _disk(0.01))
    monkeypatch.setattr(sc.DBOS, "list_queued_workflows_async", _queued(sc.QUEUE_WARN + 1))
    finding = asyncio.run(sc.run_self_check())
    assert finding["ref"] == "selfcheck:disk"
