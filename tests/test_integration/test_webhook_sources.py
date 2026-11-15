# tests/test_integration/test_webhook_sources.py
"""来源适配器:GitLab / CNB 的合并事件也走同一条发布链路。"""

import importlib
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.ingest.events import event as normalized_event

gitlab_mod = importlib.import_module("plugins.builtin.adapters.gitlab.plugin")
cnb_mod = importlib.import_module("plugins.builtin.adapters.cnb.plugin")


GITLAB_MR = {
    "object_kind": "merge_request",
    "user": {"username": "alice"},
    "project": {"id": 7, "path_with_namespace": "acme/api"},
    "object_attributes": {
        "id": 101,
        "iid": 42,
        "action": "merge",
        "state": "merged",
        "title": "修复空指针",
        "description": "修好了",
        "source_branch": "fix/npe",
        "target_branch": "main",
        "merge_commit_sha": "sha-merge",
        "url": "https://gitlab.example.com/acme/api/-/merge_requests/42",
    },
}

CNB_PR = {
    "type": "PullRequestEvent",
    "action": "closed",
    "repo": {"id": 9, "path": "acme/api"},
    "number": 42,
    "pull_request": {
        "id": 900,
        "number": 42,
        "state": "merged",
        "merged_at": "2026-11-13T10:00:00Z",
        "title": "修复空指针",
        "body": "修好了",
        "head": {"ref": "fix/npe"},
        "base": {"ref": "main"},
        "merge_commit_sha": "sha-merge",
        "html_url": "https://cnb.cool/acme/api/-/pulls/42",
    },
}


class TestGitLabEvent:
    def test_merged_merge_request(self):
        event = gitlab_mod.normalize_merge_request(GITLAB_MR)

        assert event["kind"] == "merge"
        assert event["source"] == "gitlab"
        assert event["repo"] == "acme/api"
        assert event["number"] == 42
        assert event["merge_sha"] == "sha-merge"
        assert event["base_ref"] == "main"
        assert event["head_ref"] == "fix/npe"

    def test_unmerged_merge_request_is_not_an_event(self):
        payload = {
            **GITLAB_MR,
            "object_attributes": {
                **GITLAB_MR["object_attributes"],
                "action": "open",
                "state": "opened",
            },
        }

        assert gitlab_mod.normalize_merge_request(payload) is None

    def test_non_merge_request_is_not_an_event(self):
        assert gitlab_mod.normalize_merge_request({"object_kind": "push"}) is None


class TestCNBEvent:
    def test_merged_pull_request(self):
        event = cnb_mod.normalize_pull_request_event(CNB_PR)

        assert event["kind"] == "merge"
        assert event["source"] == "cnb"
        assert event["repo"] == "acme/api"
        assert event["number"] == 42
        assert event["merge_sha"] == "sha-merge"

    def test_closed_without_merge_is_not_an_event(self):
        payload = {
            **CNB_PR,
            "pull_request": {**CNB_PR["pull_request"], "state": "closed", "merged_at": None},
        }

        assert cnb_mod.normalize_pull_request_event(payload) is None

    def test_other_event_type_is_not_an_event(self):
        assert cnb_mod.normalize_pull_request_event({"type": "PushEvent"}) is None


class TestSourceWebhookRoute:
    def _client(self, monkeypatch, source: str, captured: list):
        from engine.api.routes import webhook as webhook_mod

        class Adapter:
            def webhook_configured(self):
                return True

            def verify_webhook(self, headers, body):
                return True

            def parse_webhook(self, headers, body):
                return normalized_event(
                    kind="merge",
                    source=source,
                    repo="acme/api",
                    repo_id=9,
                    change_id=900,
                    number=42,
                    title="修复空指针",
                    base_ref="main",
                    head_ref="fix/npe",
                    merge_sha="sha-merge",
                )

        async def dedup(*args, **kwargs):
            return True

        async def enqueue(prefix, workflow, delivery_id, payload):
            captured.append((prefix, workflow.__name__, payload))
            return {"status": "queued"}

        monkeypatch.setattr(webhook_mod, "source_adapter", lambda name: Adapter())
        monkeypatch.setattr(webhook_mod, "dedup_once", dedup)
        monkeypatch.setattr(webhook_mod, "_enqueue_workflow", enqueue)

        app = FastAPI()
        app.include_router(webhook_mod.router)
        return TestClient(app)

    def test_gitlab_merge_queues_release(self, monkeypatch):
        captured: list = []
        client = self._client(monkeypatch, "gitlab", captured)

        resp = client.post(
            "/webhook/gitlab",
            content=json.dumps({"object_kind": "merge_request"}),
            headers={"X-Gitlab-Token": "s3cret", "X-Gitlab-Event-UUID": "g-1"},
        )

        assert resp.status_code == 200
        assert len(captured) == 1
        prefix, workflow_name, payload = captured[0]
        assert prefix == "gwei-release"
        assert workflow_name == "release_workflow"
        assert payload["source_adapter"] == "gitlab"
        assert payload["issue_number"] == 42
        assert payload["merge_sha"] == "sha-merge"

    def test_cnb_merge_queues_release(self, monkeypatch):
        captured: list = []
        client = self._client(monkeypatch, "cnb", captured)

        resp = client.post(
            "/webhook/cnb",
            content=json.dumps({"type": "PullRequestEvent"}),
            headers={"X-Cnb-Token": "s3cret"},
        )

        assert resp.status_code == 200
        assert len(captured) == 1
        assert captured[0][2]["source_adapter"] == "cnb"
