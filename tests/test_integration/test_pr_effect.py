# tests/test_integration/test_pr_effect.py
"""PR 作为变更单元:建分支、提交、发起合并请求;撤销是关掉它。"""

import asyncio
import importlib

from engine.change_unit import (
    ChangeUnit,
    Effect,
    JsonlLedger,
    apply,
    rollback,
    VERDICT_FAILED,
    VERDICT_KEPT,
    VERDICT_ROLLED_BACK,
)

adapter_mod = importlib.import_module("plugins.builtin.adapters.github-app.plugin")

REPO = "ChenXu233/GweiOps"


class FakeRepo:
    """只实现 PR 需要的那几个方法,行为与 GitHub 的语义一致。"""

    def __init__(self) -> None:
        # 默认分支故意不叫 main:写死 main 的实现会在这里露馅
        self.default_branch_name = "trunk"
        self.branches: dict[str, str] = {"main": "sha-main", "trunk": "sha-trunk"}
        self.commits: list[tuple[str, list, str]] = []
        self.pulls: dict[int, dict] = {}
        self.deleted: list[str] = []
        self.created_from: dict[str, str] = {}

    async def get_branch_sha(self, repo, branch):
        return self.branches.get(branch)

    async def create_branch(self, repo, branch, from_sha):
        self.branches[branch] = from_sha
        self.created_from[branch] = from_sha

    async def delete_branch(self, repo, branch):
        self.deleted.append(branch)
        self.branches.pop(branch, None)

    async def commit_files(self, repo, branch, files, message):
        self.commits.append((branch, files, message))
        self.branches[branch] = "sha-commit-%d" % len(self.commits)
        return self.branches[branch]

    async def default_branch(self, repo):
        return self.default_branch_name

    async def open_pull(self, repo, head, base, title, body=""):
        number = len(self.pulls) + 1
        self.pulls[number] = {
            "number": number,
            "base": base,
            "state": "open",
            "merged": False,
            "html_url": "https://github.com/%s/pull/%d" % (repo, number),
            "head": {"sha": self.branches.get(head, "")},
        }
        return self.pulls[number]

    async def get_pull(self, repo, number):
        return self.pulls.get(int(number))

    async def close_pull(self, repo, number):
        self.pulls[int(number)]["state"] = "closed"


def _plugin():
    plugin = adapter_mod.GitHubAppAdapter()
    plugin.client = FakeRepo()
    return plugin


def _effect(head="gwei/feature-1", base="main", files=None):
    return Effect(
        task="open_pull",
        args={
            "repo": REPO,
            "base": base,
            "head": head,
            "title": "加一个功能",
            "body": "为什么改、改了什么",
            "files": files if files is not None else [{"path": "engine/x.py", "content": "x = 1\n"}],
        },
        undo_task="close_pull",
        undo_kind="symmetric",
        capability="pr.open",
    )


def _unit(effect=None):
    return ChangeUnit(
        intent={"source": "test"},
        effect=effect or _effect(),
        binding="github",
    )


def test_pr_unit_builds_branch_commits_and_is_kept(tmp_path):
    plugin = _plugin()
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")

    out = asyncio.run(apply(_unit(), plugin, ledger))

    assert out.verdict == VERDICT_KEPT, out.reason
    assert out.handle == "1"
    # 分支是从 base 的头建出来的,之后被提交推着往前走
    assert plugin.client.created_from["gwei/feature-1"] == "sha-main"
    assert plugin.client.commits[0][1] == [{"path": "engine/x.py", "content": "x = 1\n"}]
    assert plugin.client.pulls[1]["state"] == "open"


def test_an_existing_branch_is_reused_not_recreated(tmp_path):
    plugin = _plugin()
    plugin.client.branches["gwei/feature-1"] = "sha-existing"

    out = asyncio.run(apply(_unit(), plugin, JsonlLedger(tmp_path / "l.jsonl")))

    assert out.verdict == VERDICT_KEPT
    # 已经存在的分支不该被重置到 base
    assert plugin.client.branches["gwei/feature-1"].startswith("sha-commit")


def test_rollback_closes_the_pull_and_deletes_the_branch(tmp_path):
    plugin = _plugin()
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")

    out = asyncio.run(apply(_unit(), plugin, ledger))
    again = asyncio.run(rollback(out, plugin, ledger))

    assert again.verdict == VERDICT_ROLLED_BACK
    assert plugin.client.pulls[1]["state"] == "closed"
    assert plugin.client.deleted == ["gwei/feature-1"]


def test_a_missing_base_branch_fails_without_opening_anything(tmp_path):
    """基线不存在就是确定没动:记 failed,不该记成"不知道动没动"。"""
    plugin = _plugin()
    effect = _effect(base="no-such-branch")

    out = asyncio.run(apply(_unit(effect), plugin, JsonlLedger(tmp_path / "l.jsonl")))

    assert out.verdict == VERDICT_FAILED
    assert plugin.client.pulls == {}


def test_a_merged_pull_has_no_undo_window():
    plugin = _plugin()

    async def run():
        pull = await plugin.client.open_pull(REPO, "gwei/feature-1", "main", "t")
        pull["merged"] = True
        return await plugin.window(_effect(), str(pull["number"]))

    window = asyncio.run(run())
    # 合并之后窗口就不再是"一直能撤"——那时候要撤是另一次变更
    assert window.known is False


def test_without_a_base_the_repository_says_which_branch(tmp_path):
    """调用方推不出来的东西,别让它猜:默认分支是仓库的属性。"""
    plugin = _plugin()
    effect = Effect(
        task="open_pull",
        args={
            "repo": REPO,
            "head": "gwei/feature-2",
            "title": "加个开关",
            "files": [{"path": "engine/y.py", "content": "y = 2\n"}],
        },
        undo_task="close_pull",
        undo_kind="symmetric",
        capability="pr.open",
    )

    out = asyncio.run(apply(_unit(effect), plugin, JsonlLedger(tmp_path / "l.jsonl")))

    assert out.verdict == VERDICT_KEPT, out.reason
    assert plugin.client.pulls[1]["base"] == "trunk"
    assert plugin.client.created_from["gwei/feature-2"] == "sha-trunk"


def test_missing_arguments_fail_without_touching_github(tmp_path):
    """参数不全就是确定没动过:记 failed(可重试),别让它变成"要人去核"。"""
    plugin = _plugin()
    effect = Effect(
        task="open_pull",
        args={"files": [{"path": "README.md", "content": "x"}]},
        undo_task="close_pull",
        undo_kind="symmetric",
        capability="pr.open",
    )

    out = asyncio.run(apply(_unit(effect), plugin, JsonlLedger(tmp_path / "l.jsonl")))

    assert out.verdict == VERDICT_FAILED
    assert "缺参数" in out.reason and "repo" in out.reason and "head" in out.reason
    assert plugin.client.pulls == {}


def test_paths_without_files_is_refused_not_silently_empty(tmp_path):
    """paths 只有出口会展开;直接调用时不能装作刚提交过东西。"""
    plugin = _plugin()
    effect = _effect()
    effect.args.pop("files")
    effect.args["paths"] = ["engine/x.py"]

    out = asyncio.run(apply(_unit(effect), plugin, JsonlLedger(tmp_path / "l.jsonl")))

    assert out.verdict == VERDICT_FAILED, out.reason
    assert "paths" in out.reason


def test_declared_effect_is_parsed_by_core():
    from pathlib import Path

    from engine.plugin_manager.manifest import Manifest

    manifest = Manifest.from_yaml(Path(adapter_mod.__file__).parent / "plugin.yaml")
    declared = manifest.effects["pr.open"]
    assert declared.undo_kind == "symmetric"
    assert declared.execute_task == "open_pull"
