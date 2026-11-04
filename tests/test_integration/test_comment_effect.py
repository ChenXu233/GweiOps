# tests/test_integration/test_comment_effect.py
"""评论作为变更单元:执行拿句柄、验证靠回读、撤销是删除。"""

import asyncio
import importlib

from engine.change_unit import (
    ChangeUnit,
    JsonlLedger,
    apply,
    rollback,
    VERDICT_KEPT,
    VERDICT_ROLLED_BACK,
)

adapter_mod = importlib.import_module("plugins.builtin.adapters.github-app.plugin")


class FakeClient:
    def __init__(self):
        self.comments: dict[int, dict] = {}
        self.deleted: list[int] = []
        self._next = 100

    async def create_comment(self, repo, issue_number, body):
        cid = self._next
        self._next += 1
        self.comments[cid] = {
            "id": cid,
            "body": body,
            "html_url": "https://github.com/x/%d" % cid,
        }
        return self.comments[cid]

    async def get_comment(self, repo, comment_id):
        return self.comments.get(int(comment_id))

    async def delete_comment(self, repo, comment_id):
        self.deleted.append(int(comment_id))
        self.comments.pop(int(comment_id), None)


def _plugin():
    plugin = adapter_mod.GitHubAppAdapter()
    plugin.client = FakeClient()
    return plugin


def test_comment_unit_kept_then_rolled_back(tmp_path):
    plugin = _plugin()
    effect = plugin.effect(
        "comment.create", repo="ChenXu233/GweiOps", issue_number=1, body="hello"
    )
    unit = ChangeUnit(
        intent={"source": "test"},
        effect=effect,
        binding="github",
        idempotency_key="test/1/comment",
    )
    ledger = JsonlLedger(tmp_path / "ledger.jsonl")

    out = asyncio.run(apply(unit, plugin, ledger))
    assert out.verdict == VERDICT_KEPT, out.reason
    assert out.handle == "100"
    assert int(out.handle) in plugin.client.comments
    assert out.facts["found"] is True

    again = asyncio.run(rollback(out, plugin, ledger))
    assert again.verdict == VERDICT_ROLLED_BACK
    assert plugin.client.deleted == [100]
    assert plugin.client.comments == {}
    assert len(ledger.read()) == 2


def test_binding_must_match_github():
    plugin = _plugin()
    effect = plugin.effect(
        "comment.create", repo="ChenXu233/GweiOps", issue_number=1, body="x"
    )
    unit = ChangeUnit(intent={}, effect=effect, binding="somewhere-else")
    try:
        asyncio.run(apply(unit, plugin))
    except ValueError as e:
        assert "binding" in str(e)
    else:
        raise AssertionError("绑定不一致必须被拒")


def test_declared_effect_matches_manifest():
    plugin = _plugin()
    declared = plugin.effects()["comment.create"]
    assert declared["undo"]["kind"] == "symmetric"
    assert declared["execute"]["task"] == "create_comment"
