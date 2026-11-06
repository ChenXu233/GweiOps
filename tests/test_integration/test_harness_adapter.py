# tests/test_integration/test_harness_adapter.py
"""外部 harness:在工作区里跑一条命令,收回一份报告。边界由那条命令决定。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from engine.harness import build_task, run_harness
from engine.shared.config import config
from engine.workflows import pipeline

SIGNAL = {"source": "alertmanager", "subject": "high-error", "title": "错误率超 10%"}


def _py(script: str) -> str:
    """一条跨平台的假 harness:用当前解释器跑一段脚本。"""
    return f'"{sys.executable}" -c "{script}"'


def _writes(payload: dict) -> str:
    body = json.dumps(payload).replace('"', '\\"')
    return _py(
        "import os,json;"
        f"open(os.environ['GWEI_REPORT'],'w',encoding='utf-8').write('{body}')"
    )


def test_the_task_says_where_the_exits_and_the_report_are():
    task = build_task(
        incident_id="inc-9",
        signal=SIGNAL,
        exit_url="http://gw/api/agent/exits",
        workspace="/w/inc-9",
        report_path="/w/inc-9/report.json",
    )
    assert "inc-9" in task
    assert "http://gw/api/agent/exits" in task
    assert "/w/inc-9/report.json" in task
    assert SIGNAL["title"] in task


def test_a_report_is_picked_up(tmp_path):
    result = asyncio.run(
        run_harness(
            command=_writes({"summary": "加了副本", "steps": [], "counts": {"kept": 1}, "exhausted": False}),
            workspace=tmp_path / "inc-1",
            task="whatever",
        )
    )
    assert result.report["summary"] == "加了副本"
    assert result.report["source"] == "harness"
    assert (tmp_path / "inc-1" / "task.md").exists()


def test_the_exit_url_and_report_path_reach_the_command(tmp_path):
    # 嵌套引号在 cmd.exe 里不可靠,脚本落成文件再调用
    script = tmp_path / "echo_env.py"
    script.write_text(
        "import os, json\n"
        "open(os.environ['GWEI_REPORT'], 'w', encoding='utf-8').write(\n"
        "    json.dumps({'summary': os.environ['GWEI_EXIT_URL'] + '|' + os.environ['GWEI_INCIDENT_ID']})\n"
        ")\n",
        encoding="utf-8",
    )
    result = asyncio.run(
        run_harness(
            command=f'"{sys.executable}" "{script}"',
            workspace=tmp_path / "inc-2",
            task="x",
            extra_env={"GWEI_EXIT_URL": "http://gw/api/agent/exits", "GWEI_INCIDENT_ID": "inc-2"},
        )
    )
    assert result.report["summary"] == "http://gw/api/agent/exits|inc-2"


def test_a_silent_harness_still_gets_a_report(tmp_path):
    """没交报告不是"什么都没发生",是一条要被人看见的结论。"""
    result = asyncio.run(
        run_harness(command=_py("print('hello')"), workspace=tmp_path / "inc-3", task="x")
    )
    assert "没有交报告" in result.report["summary"]
    assert "hello" in result.report["summary"]
    assert result.report["source"] == "harness"


def test_a_hung_harness_is_cut_off_and_said_so(tmp_path):
    result = asyncio.run(
        run_harness(
            command=_py("import time; time.sleep(10)"),
            workspace=tmp_path / "inc-4",
            task="x",
            timeout_s=0.3,
        )
    )
    assert result.timed_out is True
    assert result.report["exhausted"] is True
    assert "超时" in result.report["summary"]


def test_the_workspace_placeholder_is_substituted(tmp_path):
    workspace = tmp_path / "inc-5"
    result = asyncio.run(
        run_harness(
            command=_py("import os;print(os.getcwd())").replace("{workspace}", str(workspace)),
            workspace=workspace,
            task="x",
        )
    )
    assert str(workspace) in result.report["summary"]


# ---------------------------------------------------------------------------
# 工作流:配了 harness 才走它
# ---------------------------------------------------------------------------


class FakeDBOS:
    workflow_id = "wf-h"


def test_without_a_command_the_harness_is_skipped(monkeypatch):
    monkeypatch.setattr(config.settings, "harness_command", "")
    assert asyncio.run(
        pipeline._run_harness_impl({"signal": dict(SIGNAL), "tenant_slug": "acme"})
    ) is None


def test_with_a_command_the_report_comes_back(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "DBOS", FakeDBOS)
    monkeypatch.setattr(config.settings, "harness_command", _writes({"summary": "搞定了"}))
    monkeypatch.setattr(config.settings, "harness_workspace_root", str(tmp_path))

    report = asyncio.run(
        pipeline._run_harness_impl({"signal": dict(SIGNAL), "tenant_slug": "acme"})
    )
    assert report["summary"] == "搞定了"
    assert (tmp_path / "wf-h" / "report.json").exists()
