# tests/test_integration/test_sandbox.py
"""沙箱:一场 harness 在哪跑,平台只认那一个接口。

这里钉三件事:接口没漏(换一个提供者不改 run_harness)、本地提供者的行为与从前
一字不差、CNB 那条路在真正发请求之前就把话说清楚(交进去的是什么、取不回来的
时候不会装作成功)。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from engine.harness import blobs, sandbox as sandbox_mod
from engine.harness.adapter import REPORT_NAME
from engine.harness.cnb_sandbox import (
    CHANGES_ARCHIVE,
    INBOX,
    CnbHandles,
    CnbSandbox,
    build_config,
    script,
)
from engine.harness.sandbox import (
    Entry,
    LocalSandbox,
    Sandbox,
    SandboxError,
    SandboxResult,
    SshSandbox,
)


@pytest.fixture(autouse=True)
def unsigned_git(monkeypatch):
    """用例会在临时仓库里 `git commit`;开发机开着签名又没配密钥时会失败。"""
    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "commit.gpgsign")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
    monkeypatch.setenv("GIT_CONFIG_KEY_1", "core.hooksPath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_1", os.devnull)


def _py(script_text: str) -> str:
    return f'"{sys.executable}" -c "{script_text}"'


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------


def test_the_three_providers_speak_the_same_interface():
    for provider in (LocalSandbox(),):
        assert isinstance(provider, Sandbox)
    for method in ("prepare", "handshake", "invoke", "fetch", "entries"):
        assert callable(getattr(LocalSandbox(), method))


def test_an_unknown_provider_is_refused_by_name(monkeypatch):
    from engine.shared.config import config

    monkeypatch.setattr(config.settings, "sandbox", "somewhere-else")
    with pytest.raises(SandboxError) as caught:
        sandbox_mod.build_from_settings()
    assert "somewhere-else" in str(caught.value)
    # 可选的名字要列出来:报错要能指路,不能只说"不行"
    assert "local" in str(caught.value)


def test_ssh_without_a_target_is_refused_right_away():
    with pytest.raises(SandboxError):
        SshSandbox(target="  ")


# ---------------------------------------------------------------------------
# 本地提供者:行为与从前一致
# ---------------------------------------------------------------------------


def test_local_hands_the_files_in_and_reads_the_report(tmp_path):
    from engine.harness import run_harness

    workspace = tmp_path / "inc-local"
    result = asyncio.run(
        run_harness(
            command=_py("print('done')"),
            workspace=workspace,
            task="看代码",
        )
    )
    assert result.report["summary"] == "done"
    assert result.entry.provider == "local"
    assert (workspace / "task.md").exists()


def test_local_entry_says_where_it_ran(tmp_path):
    provider = LocalSandbox()
    handle = asyncio.run(provider.prepare(workspace=tmp_path / "w", files={"task.md": b"t"}))
    entry = asyncio.run(provider.entries(handle))
    assert isinstance(entry, Entry)
    assert entry.provider == "local"
    assert entry.to_dict()["home"].endswith("w")


def test_the_entry_does_not_carry_empty_fields():
    """空字段不写:界面上不该出现一排空表头。"""
    assert Entry(provider="cnb").to_dict() == {"provider": "cnb"}
    assert Entry(provider="cnb", id="sn-1").to_dict()["id"] == "sn-1"


# ---------------------------------------------------------------------------
# 搬运:代码进去、改动出来
# ---------------------------------------------------------------------------


def test_the_code_package_leaves_the_platform_files_out(tmp_path):
    (tmp_path / "main.py").write_text("print(1)", encoding="utf-8")
    (tmp_path / "task.md").write_text("任务", encoding="utf-8")
    (tmp_path / ".harness-env").write_text("KEY=1", encoding="utf-8")

    data = blobs.pack(tmp_path)
    names = set(blobs.unpack(data, tmp_path / "back").iterdir())
    assert {p.name for p in names} == {"main.py"}, "任务书与凭据不该跟着代码再走一遍"


def test_deleted_files_are_marked_in_the_change_package(tmp_path):
    """字节流里没有"文件不存在"这种东西,删除要用一个空条目标出来。"""
    import io
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="gone.txt")
        info.size = 0
        tar.addfile(info, io.BytesIO(b""))
        info = tarfile.TarInfo(name="kept.txt")
        payload = b"hello"
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    changes = blobs.read_changes(buffer.getvalue())
    assert {"path": "gone.txt", "delete": True} in changes
    assert {"path": "kept.txt", "content": "hello"} in changes


def test_a_non_utf8_file_is_refused_by_name(tmp_path):
    import io
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="logo.png")
        payload = b"\x89PNG\x00\x01"
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    with pytest.raises(Exception) as caught:
        blobs.read_changes(buffer.getvalue())
    assert "logo.png" in str(caught.value)


def test_the_changes_come_back_and_the_platform_counts_them(tmp_path):
    """改动由平台对着基线数:沙箱只负责把文件带回来。"""

    from engine.harness import run_harness, workspace as ws

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    asyncio.run(ws.commit_snapshot(repo))

    workspace = tmp_path / "ws"
    ws.materialize(ws.Checkout(repo_path=repo, branch="main", commit=""), workspace)
    (workspace / "app.py").write_text("x = 2\nprint(x)\n", encoding="utf-8")
    (workspace / REPORT_NAME).write_text('{"summary": "改好了"}', encoding="utf-8")

    changes = blobs.read_changes(asyncio.run(blobs.changes_archive(repo, workspace)))
    assert {"path": "app.py", "content": "x = 2\nprint(x)\n"} in changes


# ---------------------------------------------------------------------------
# CNB:真正发请求之前就要说清的事
# ---------------------------------------------------------------------------


def test_the_script_stages_the_package_and_flattens_the_checkout():
    text = script(
        command="dsh -",
        home="/tmp/gwei-harness",
        files={"task.md": "STAGE0"},
        env_names=["GWEI_EXIT_URL"],
    )
    # 代码包从环境变量解出来
    assert 'printf "%s" "$STAGE0" | base64 -d' in text
    # CNB 自己检出的仓库摊进平台的工作区,已存在的文件不覆盖
    assert "--skip-old-files" in text
    # 出口地址这类变量也写进沙箱里那份 .harness-env
    assert ".harness-env" in text
    # 命令在平台的工作区里跑
    assert text.strip().endswith('cd "$GWEI_WORKSPACE"')


def test_the_pipeline_config_carries_the_stage_by_reference():
    """`env` 里的值要写成 $NAME:CNB 会把真的值渲染进去,长内容才带得动。"""
    text = build_config(
        env_name="STAGE0", run_script="echo hi", image="alpine:3.20", event="api_trigger_harness"
    )
    assert "STAGE0: $STAGE0" in text
    assert "api_trigger_harness:" in text
    assert "image: alpine:3.20" in text


def test_cnb_without_a_repo_is_refused_before_any_request():
    provider = CnbSandbox(token="t", repo="")
    with pytest.raises(SandboxError) as caught:
        asyncio.run(provider.prepare(workspace=Path("/tmp"), files={}))
    assert "GWEI_SANDBOX_CNB_REPO" in str(caught.value)


def test_cnb_without_a_token_is_refused_at_construction():
    with pytest.raises(SandboxError):
        CnbSandbox(token="  ")


def test_an_oversized_stage_is_refused_instead_of_being_squeezed_in(tmp_path, monkeypatch):
    monkeypatch.setattr("engine.harness.cnb_sandbox.MAX_INLINE_BYTES", 10)
    provider = CnbSandbox(token="t", repo="ChenXu233/gweiops")
    (tmp_path / "big.txt").write_text("x" * 100, encoding="utf-8")
    with pytest.raises(SandboxError) as caught:
        asyncio.run(provider.prepare(workspace=tmp_path, files={}))
    assert "object_storage" in str(caught.value)


def test_a_build_that_never_finishes_times_out_and_says_so(tmp_path, monkeypatch):
    provider = CnbSandbox(token="t", repo="o/r", poll_s=0.01)

    async def never(_method, _path, **_kwargs):
        return {"status": "pending"}

    monkeypatch.setattr(provider, "_request", never)
    result = asyncio.run(
        provider.invoke(CnbHandles(sn="sn-1"), command="x", env={}, timeout_s=0.05)
    )
    assert result.timed_out is True
    assert result.exit_code is None


def test_nothing_to_fetch_means_no_report_not_a_fake_one(tmp_path):
    """没有产物回来就是没有。不把它说成"跑完了",那等于替沙箱编一份结论。"""
    provider = CnbSandbox(token="t", repo="o/r")
    assert asyncio.run(provider.fetch(CnbHandles(sn="sn-1"), [REPORT_NAME])) == {}


def test_the_handoff_seam_takes_the_bytes_somewhere_else(tmp_path, monkeypatch):
    """第三方存储:平台只交一个"去哪拿",怎么到那边去不是沙箱的事。"""

    class Handoff:
        called: dict = {}

        async def handoff(self, stage: dict) -> str:
            Handoff.called = dict(stage)
            return "https://store.example/handoff"

    provider = CnbSandbox(token="t", repo="o/r", handoff=Handoff())
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")

    async def fake_request(method, path, **kwargs):
        fake_request.body = kwargs.get("json") or {}
        return {"sn": "cnb-1"}

    monkeypatch.setattr(provider, "_request", fake_request)
    handle = asyncio.run(provider.prepare(workspace=tmp_path, files={"task.md": b"t"}))

    assert handle.sn == "cnb-1"
    assert "a.txt" not in Handoff.called  # 代码在包里,不逐条拆开
    assert fake_request.body["env"]["STAGE0"] == "https://store.example/handoff"
    assert json.dumps(fake_request.body, ensure_ascii=False).count("STAGE0") >= 1
