# tests/test_integration/test_workspace.py
"""工作区里的代码:铺进来的是文件,收上去的是改动。

这一层要回答的问题只有一个:agent 在工作区里改过的东西,平台能不能一字不差地
读出来——读漏了会少提交一个文件,读多了会把平台自己的东西混进提交里。
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from engine.harness import workspace as ws

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="本机没有 git")


def _git(*args: str, cwd: Path) -> str:
    out = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        check=True,
        text=True,
    )
    return out.stdout


@pytest.fixture
def repo(tmp_path) -> ws.Checkout:
    """一份有提交的仓库副本:这就是平台拉下来之后留着的那份。"""
    path = tmp_path / ws.REPO_DIR / "inc-1"
    path.mkdir(parents=True)
    (path / "app.py").write_text("print('v1')\n", encoding="utf-8")
    (path / "README.md").write_text("# demo\n", encoding="utf-8")
    (path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    _git("init", "-q", "-b", "main", cwd=path)
    _git("add", "-A", cwd=path)
    _git(
        "-c", "user.email=gwei@example.invalid",
        "-c", "user.name=gwei",
        "commit", "-q", "-m", "init",
        cwd=path,
    )
    return ws.Checkout(repo_path=path, branch="main", commit=_git("rev-parse", "HEAD", cwd=path).strip())


@pytest.fixture
def work(tmp_path, repo) -> Path:
    """铺给 harness 的那一层:没有 .git。"""
    path = tmp_path / "inc-1"
    ws.materialize(repo, path)
    return path


def _collect(repo, work, paths=None):
    return asyncio.run(ws.collect(repo.repo_path, work, paths))


def test_the_workspace_gets_the_files_but_not_the_repository(repo, work):
    assert (work / "app.py").read_text(encoding="utf-8") == "print('v1')\n"
    assert not (work / ".git").exists(), "容器里的那份不该带 .git,凭据和提交都不在那"


def test_nothing_changed_is_said_out_loud(repo, work):
    with pytest.raises(ws.WorkspaceError, match="没有改动"):
        _collect(repo, work)


def test_modified_added_and_deleted_files_all_come_back(repo, work):
    (work / "app.py").write_text("print('v2')\n", encoding="utf-8", newline="\n")
    (work / "feature.py").write_text("x = 1\n", encoding="utf-8", newline="\n")
    (work / "README.md").unlink()

    files = {item["path"]: item for item in _collect(repo, work)}

    assert files["app.py"]["content"] == "print('v2')\n"
    assert files["feature.py"]["content"] == "x = 1\n"
    assert files["README.md"] == {"path": "README.md", "delete": True}


def test_platform_files_in_the_workspace_are_not_part_of_the_change(repo, work):
    """task.md / report.json 是平台自己写的,混进提交就成了"agent 改的"。"""
    (work / "app.py").write_text("print('v3')\n", encoding="utf-8", newline="\n")
    (work / "task.md").write_text("任务", encoding="utf-8")
    (work / "report.json").write_text("{}", encoding="utf-8")

    paths = [item["path"] for item in _collect(repo, work)]

    assert paths == ["app.py"]


def test_ignored_paths_stay_out(repo, work):
    """仓库自己说 node_modules 不进版本库,那它也不进这次提交。"""
    (work / "app.py").write_text("print('v4')\n", encoding="utf-8", newline="\n")
    junk = work / "node_modules" / "lib"
    junk.mkdir(parents=True)
    (junk / "index.js").write_text("1", encoding="utf-8")

    paths = [item["path"] for item in _collect(repo, work)]

    assert paths == ["app.py"]


def test_paths_narrow_the_change(repo, work):
    (work / "app.py").write_text("print('v5')\n", encoding="utf-8", newline="\n")
    (work / "feature.py").write_text("y = 2\n", encoding="utf-8", newline="\n")

    files = _collect(repo, work, ["feature.py"])

    assert [item["path"] for item in files] == ["feature.py"]


def test_a_path_outside_the_workspace_is_refused(repo, work):
    with pytest.raises(ws.WorkspaceError, match="跑出工作区"):
        _collect(repo, work, ["../escape.py"])


def test_a_binary_file_is_refused_by_name(repo, work):
    (work / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    (work / "app.py").write_text("print('v6')\n", encoding="utf-8", newline="\n")

    with pytest.raises(ws.WorkspaceError, match="logo.png"):
        _collect(repo, work)


def test_an_oversized_file_is_refused_with_its_size(repo, work, monkeypatch):
    monkeypatch.setattr(ws, "MAX_FILE_BYTES", 16)
    (work / "big.txt").write_text("x" * 64, encoding="utf-8")

    with pytest.raises(ws.WorkspaceError, match="big.txt"):
        _collect(repo, work)


def test_too_many_files_is_refused(repo, work, monkeypatch):
    monkeypatch.setattr(ws, "MAX_FILES", 1)
    (work / "a.txt").write_text("a", encoding="utf-8")
    (work / "b.txt").write_text("b", encoding="utf-8")

    with pytest.raises(ws.WorkspaceError, match="上限"):
        _collect(repo, work)


def test_an_incident_id_cannot_walk_out_of_the_root(tmp_path):
    with pytest.raises(ws.WorkspaceError, match="目录名"):
        ws.workspace_of(tmp_path, "../../etc")

    assert ws.workspace_of(tmp_path, "wf-1234") == tmp_path / "wf-1234"
    assert ws.repo_of(tmp_path, "wf-1234") == tmp_path / ws.REPO_DIR / "wf-1234"


def test_materialize_clears_what_the_last_run_left(tmp_path, repo):
    path = tmp_path / "inc-stale"
    path.mkdir()
    (path / "leftover.py").write_text("上一场留下的", encoding="utf-8")

    ws.materialize(repo, path)

    assert not (path / "leftover.py").exists()
    assert (path / "app.py").exists()


def test_the_exit_reads_the_workspace_for_the_incident(tmp_path, repo, work, monkeypatch):
    """出口那一侧:incident_id → 工作区 → files。"""
    from engine.api.routes.agent import _workspace_files
    from engine.shared.config import config

    monkeypatch.setattr(config.settings, "harness_workspace_root", str(tmp_path))
    (work / "app.py").write_text("print('v7')\n", encoding="utf-8", newline="\n")

    files = asyncio.run(_workspace_files("inc-1", None))

    assert files == [{"path": "app.py", "content": "print('v7')\n"}]


def test_the_exit_says_so_when_there_is_no_incident(tmp_path, monkeypatch):
    from engine.api.routes.agent import _workspace_files
    from engine.shared.config import config

    monkeypatch.setattr(config.settings, "harness_workspace_root", str(tmp_path))

    with pytest.raises(ws.WorkspaceError, match="incident_id"):
        asyncio.run(_workspace_files("", None))
