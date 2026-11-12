# tests/test_integration/test_harness_adapter.py
"""外部 harness:在工作区里跑一条命令,收回一份报告。边界由那条命令决定。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from engine.harness import ENV_FILE_NAME, build_task, run_harness
from engine.harness.adapter import _write_env_file
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


def test_the_task_says_how_to_authenticate():
    """让 agent 去猜 401 该怎么办,它只会把时间花在翻环境变量上。"""
    task = build_task(
        incident_id="inc-9",
        signal=SIGNAL,
        exit_url="http://gw/api/agent/exits",
        workspace="/w/inc-9",
        report_path="/w/inc-9/report.json",
        token="gwei-harness-abc",
    )
    assert "X-Gwei-Token: gwei-harness-abc" in task


def test_without_a_token_no_header_is_invented():
    task = build_task(
        incident_id="inc-9",
        signal=SIGNAL,
        exit_url="http://gw/api/agent/exits",
        workspace="/w/inc-9",
        report_path="/w/inc-9/report.json",
    )
    assert "X-Gwei-Token" not in task


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


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 上 chmod 不表达组/其他位的权限")
def test_the_workspace_is_writable_by_the_harness_container(tmp_path):
    """两端 uid 不同(引擎 gwei / 镜像里的 node),工作区必须对它开放写权限。"""
    workspace = tmp_path / "inc-perm"
    asyncio.run(run_harness(command=_writes({"summary": "ok"}), workspace=workspace, task="t"))

    mode = workspace.stat().st_mode & 0o777
    assert mode & 0o002, f"其他用户不可写:{oct(mode)}"


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


def test_the_env_the_harness_needs_is_on_disk(tmp_path):
    """命令里逐个 -e 点名太容易漏;--env-file 一次带进去,谁能用谁用。"""
    script = tmp_path / "read_env.py"
    script.write_text(
        "import os, json\n"
        "open(os.environ['GWEI_REPORT'], 'w', encoding='utf-8').write(\n"
        "    json.dumps({'summary': os.environ.get('SOME_TOKEN', 'missing')})\n"
        ")\n",
        encoding="utf-8",
    )
    workspace = tmp_path / "inc-env"
    env_file = workspace / ENV_FILE_NAME

    result = asyncio.run(
        run_harness(
            command=(
                f'"{sys.executable}" "{script}" '
                f'--env-file "{env_file}"'
            ),
            workspace=workspace,
            task="x",
            extra_env={"SOME_TOKEN": "abc123"},
        )
    )

    assert env_file.exists()
    # 值带换行就写不进去:那种东西不该塞进 env 文件里假装成功
    content = env_file.read_text(encoding="utf-8")
    assert "SOME_TOKEN=abc123" in content
    assert "GWEI_" not in content.replace("SOME_TOKEN", "")


def test_a_multiline_value_is_left_out_of_the_env_file(tmp_path):
    path = _write_env_file(tmp_path, {"ok": "1", "pem": "-----BEGIN\nabc\n-----END"})

    text = path.read_text(encoding="utf-8")
    assert "ok=1" in text
    assert "pem" not in text


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
