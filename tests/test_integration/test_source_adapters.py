# tests/test_integration/test_source_adapters.py
"""来源适配器收口:"这条投递来自谁"只有一个答案。

三条曾经写死的地方 —— 回哪个来源、拿哪家的代码、评论里叫什么 —— 都归适配器声明。
这里钉住的是"没有来源就不猜",以及 CNB 的议题/评论事件真的能进来。
"""

import asyncio

import pytest

from engine.ingest.events import event as normalized_event
from engine.ingest.source import mentions_of, mentions_prompt, source_adapter


class _Adapter:
    def __init__(self, source="cnb", mentions=("@codebuddy",)):
        self.source = source
        self.mentions = mentions

    async def workspace_source(self, repo):
        from engine.harness.workspace import Source

        return Source(archive_url=f"https://example.invalid/{repo}.tar.gz", branch="main")


class TestSourceResolution:
    def test_an_unknown_source_is_an_error_not_a_default_adapter(self, monkeypatch):
        """没有 CNB 适配器时不能拿 GitHub 的顶上:那会去拉另一个仓库的代码。"""
        import engine.shared.runtime as runtime
        from engine.plugin_manager import registry

        monkeypatch.setattr(registry, "webhook_adapter", lambda source: None)

        with pytest.raises(LookupError) as exc:
            runtime.get_adapter("cnb")
        assert "cnb" in str(exc.value)

    def test_the_registry_decides_which_adapter(self, monkeypatch):
        import engine.shared.runtime as runtime
        from engine.plugin_manager import registry

        adapter = _Adapter()
        monkeypatch.setattr(registry, "webhook_adapter", lambda source: adapter)

        assert runtime.get_adapter("cnb") is adapter

    def test_no_source_means_no_adapter(self):
        with pytest.raises(LookupError):
            source_adapter("")


class TestMentions:
    def test_the_trigger_word_comes_from_the_adapter(self):
        adapter = _Adapter(mentions=("@CodeBuddy",))

        assert mentions_of(adapter) == ("@codebuddy",)
        assert mentions_prompt(adapter, "请 @CodeBuddy 看一下") is True
        assert mentions_prompt(adapter, "我 @gwei 了") is False

    def test_an_adapter_without_mentions_takes_no_comment_triggers(self):
        """没声明就是没接评论触发:不继承别人的名字。"""
        assert mentions_prompt(_Adapter(mentions=()), "@gwei 修一下") is False


class TestCNBIssueAndComment:
    def _mod(self):
        import importlib

        return importlib.import_module("plugins.builtin.adapters.cnb.plugin")

    def test_an_opened_issue_becomes_a_triage_event(self):
        payload = {
            "type": "IssueEvent",
            "action": "opened",
            "repo": {"id": 9, "path": "acme/api"},
            "issue": {"id": 500, "number": 7, "title": "登录页白屏", "body": "点了没反应"},
            "sender": {"username": "alice"},
        }

        event = self._mod().normalize_event(payload)

        assert event["kind"] == "issue"
        assert event["source"] == "cnb"
        assert event["repo"] == "acme/api"
        assert event["number"] == 7
        assert event["body"] == "点了没反应"

    def test_a_comment_on_an_issue(self):
        payload = {
            "type": "IssueCommentEvent",
            "action": "created",
            "repo": {"id": 9, "path": "acme/api"},
            "issue": {"id": 500, "number": 7, "title": "登录页白屏"},
            "comment": {"id": 1, "body": "@CodeBuddy 帮我修一下"},
        }

        event = self._mod().normalize_event(payload)

        assert event["kind"] == "comment"
        assert event["body"] == "@CodeBuddy 帮我修一下"
        assert event["is_pull"] is False

    def test_a_comment_on_a_pull_request_knows_it_is_a_pull(self):
        """CNB 上 PR 评论与议题评论是两个地址,回评得知道落在哪一边。"""
        payload = {
            "type": "IssueCommentEvent",
            "action": "created",
            "repo": {"id": 9, "path": "acme/api"},
            "pull_request": {"id": 900, "number": 42, "title": "修复空指针"},
            "comment": {"id": 2, "body": "@CodeBuddy 再改一版"},
        }

        event = self._mod().normalize_event(payload)

        assert event["kind"] == "comment"
        assert event["is_pull"] is True
        assert event["number"] == 42

    def test_unrelated_types_are_not_events(self):
        assert self._mod().normalize_event({"type": "PushEvent"}) is None


class TestWorkspaceSourceIsTheSourcesOwn:
    def test_the_adapter_hands_over_its_own_archive(self):
        from engine.ingest.source import workspace_source_of

        source = asyncio.run(workspace_source_of(_Adapter(), "acme/api"))

        assert source.archive_url.endswith("acme/api.tar.gz")
        assert source.branch == "main"

    def test_an_adapter_without_a_workspace_cannot_start_a_run(self):
        from engine.ingest.source import workspace_source_of

        class Bare:
            source = "nobody"

        with pytest.raises(LookupError):
            asyncio.run(workspace_source_of(Bare(), "acme/api"))


class TestReplyGoesBackToTheSameSource:
    def test_the_reply_binding_is_the_delivery_source(self):
        from engine.workflows.pipeline import reply_binding

        assert reply_binding({"source_adapter": "cnb"}) == "cnb"

    def test_a_payload_without_a_source_is_refused(self):
        from engine.workflows.pipeline import reply_binding

        with pytest.raises(LookupError):
            reply_binding({"repo_full_name": "acme/api"})


class TestCommentTriggerAtTheEntry:
    def _client(self, monkeypatch, adapter):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from engine.api.routes import webhook as webhook_mod

        captured: list = []

        async def dedup(*args, **kwargs):
            return True

        async def enqueue(prefix, workflow, delivery_id, payload):
            captured.append((prefix, workflow.__name__, payload))
            return {"status": "queued"}

        monkeypatch.setattr(webhook_mod, "source_adapter", lambda name: adapter)
        monkeypatch.setattr(webhook_mod, "dedup_once", dedup)
        monkeypatch.setattr(webhook_mod, "_enqueue_workflow", enqueue)

        app = FastAPI()
        app.include_router(webhook_mod.router)
        return TestClient(app), captured

    def test_a_cnb_comment_naming_the_npc_starts_a_run(self, monkeypatch):
        class Cnbd(_Adapter):
            def webhook_configured(self):
                return True

            def verify_webhook(self, headers, body):
                return True

            def parse_webhook(self, headers, body):
                return normalized_event(
                    kind="comment",
                    source="cnb",
                    repo="acme/api",
                    number=7,
                    body="@CodeBuddy 帮我修一下",
                )

        client, captured = self._client(monkeypatch, Cnbd())

        resp = client.post("/webhook/cnb", content=b"{}")

        assert resp.status_code == 200
        assert captured[0][0] == "gwei-fix"
        assert captured[0][2]["source_adapter"] == "cnb"

    def test_a_comment_that_names_someone_else_is_ignored(self, monkeypatch):
        class Cnbd(_Adapter):
            mentions = ("@codebuddy",)

            def webhook_configured(self):
                return True

            def verify_webhook(self, headers, body):
                return True

            def parse_webhook(self, headers, body):
                return normalized_event(
                    kind="comment",
                    source="cnb",
                    repo="acme/api",
                    number=7,
                    body="@someoneelse 看一下",
                )

        client, captured = self._client(monkeypatch, Cnbd())

        resp = client.post("/webhook/cnb", content=b"{}")

        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"
        assert captured == []

    def test_gitlab_does_not_borrow_githubs_trigger_word(self, monkeypatch):
        """`@gwei` 是 GitHub 适配器声明的;没声明的来源不该因此开始接评论。"""
        class Gitlab(_Adapter):
            source = "gitlab"
            mentions = ()

            def webhook_configured(self):
                return True

            def verify_webhook(self, headers, body):
                return True

            def parse_webhook(self, headers, body):
                return normalized_event(
                    kind="comment", source="gitlab", repo="acme/api", number=7, body="@gwei 修"
                )

        client, captured = self._client(monkeypatch, Gitlab())

        resp = client.post("/webhook/gitlab", content=b"{}")

        assert resp.json()["status"] == "ignored"
        assert captured == []
