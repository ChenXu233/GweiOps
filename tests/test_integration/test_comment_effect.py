# tests/test_integration/test_comment_effect.py
"""评论作为变更单元:执行拿句柄、验证靠回读、撤销是删除。"""

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
    VERDICT_UNKNOWN,
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


def _comment_effect(repo="ChenXu233/GweiOps", issue_number=1, body="hello"):
    return Effect(
        task="create_comment",
        args={"repo": repo, "issue_number": issue_number, "body": body},
        undo_task="delete_comment",
        undo_kind="symmetric",
        capability="comment.create",
    )


def _plugin():
    plugin = adapter_mod.GitHubAppAdapter()
    plugin.client = FakeClient()
    return plugin


def test_comment_unit_kept_then_rolled_back(tmp_path):
    plugin = _plugin()
    effect = _comment_effect()
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
    assert len(asyncio.run(ledger.read())) == 2


def test_binding_must_match_github():
    plugin = _plugin()
    effect = _comment_effect(body="x")
    unit = ChangeUnit(intent={}, effect=effect, binding="somewhere-else")
    try:
        asyncio.run(apply(unit, plugin))
    except ValueError as e:
        assert "binding" in str(e)
    else:
        raise AssertionError("绑定不一致必须被拒")


class RejectingClient(FakeClient):
    """按给定的异常失败,用来验证"这次到底碰到 GitHub 没有"的判定。"""

    def __init__(self, exc: BaseException):
        super().__init__()
        self.exc = exc

    async def create_comment(self, repo, issue_number, body):
        raise self.exc


def _apply_with(exc: BaseException):
    plugin = _plugin()
    plugin.client = RejectingClient(exc)
    unit = ChangeUnit(intent={"source": "test"}, effect=_comment_effect(), binding="github")
    return asyncio.run(apply(unit, plugin))


def _http_failure(status: int):
    """造一个真的 RequestFailed:githubkit 要自己的 Response 包装,内部才拿得到 raw_request。"""
    import httpx
    from githubkit.exception import RequestFailed
    from githubkit.response import Response as GitHubResponse

    req = httpx.Request("POST", "https://api.github.com/repos/a/b/issues/1/comments")
    return RequestFailed(GitHubResponse(httpx.Response(status, request=req), dict))


def test_client_side_failure_is_failed_not_unknown():
    """请求根本没发出去(缺 auth-app extra、JWT 签不出来):下游一个字节都没变。"""
    from githubkit.exception import RequestError

    unit = _apply_with(RequestError(ValueError("JWT support should be installed")))
    assert unit.verdict == VERDICT_FAILED
    assert "确定没动" in unit.reason
    # 原始错因留在事实里:换掉的只是结论,不是证据
    assert "JWT support" in unit.facts["error"]["message"]


def test_4xx_is_failed_because_github_said_no():
    """404 是发出去被明确拒了,同样什么都没留下。"""
    assert _apply_with(_http_failure(404)).verdict == VERDICT_FAILED
    assert _apply_with(_http_failure(403)).verdict == VERDICT_FAILED


def test_5xx_is_unknown_because_it_may_have_landed():
    """5xx 说不清:服务端可能已经建了评论,只是回程丢了。不能教人放心重试。"""
    unit = _apply_with(_http_failure(502))
    assert unit.verdict == VERDICT_UNKNOWN
    assert "不知道动没动" in unit.reason


def test_declared_effect_is_parsed_by_core():
    from pathlib import Path

    from engine.plugin_manager.manifest import Manifest

    manifest = Manifest.from_yaml(Path(adapter_mod.__file__).parent / "plugin.yaml")
    declared = manifest.effects["comment.create"]
    assert declared.undo_kind == "symmetric"
    assert declared.execute_task == "create_comment"
