# tests/test_integration/test_release_workflow.py
"""合并即发布:合并事件 → 发布意图 → 指定下游的变更单元。"""

import asyncio
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.shared.config import config
from engine.workflows.release import (
    build_release_intent,
    missing_release_config,
    release_config,
    release_skip_reason,
)

PAYLOAD = {
    "tenant_slug": "default",
    "repo_full_name": "acme/api",
    "issue_number": 42,
    # 回评落到哪,由这条投递的来源决定:不写就是没有来源,平台不替它猜一家
    "source_adapter": "github",
    "merge_sha": "0123456789abcdef0123456789abcdef01234567",
    "base_ref": "main",
    "head_ref": "gwei/fix-1",
}

RAW = {
    "repository": {
        "id": 9,
        "name": "api",
        "owner": {"login": "acme"},
    },
    "pull_request": {
        "id": 77,
        "number": 42,
        "title": "修复空指针",
        "body": "修好了",
        "merged": True,
        "merge_commit_sha": PAYLOAD["merge_sha"],
        "base": {"ref": "main"},
        "head": {"ref": "gwei/fix-1"},
    },
}


def _configure(monkeypatch, **values):
    for key, value in values.items():
        monkeypatch.setattr(config.settings, key, value)


def test_intent_uses_merge_commit_and_image_template(monkeypatch):
    _configure(
        monkeypatch,
        release_project_dir="/srv/api",
        release_service="api",
        release_image_template="ghcr.io/{repo}:{sha}",
        release_base_branch="main",
        release_binding="local",
    )

    intent = build_release_intent(PAYLOAD)

    assert intent is not None
    effect = intent["effects"][0]
    assert effect["capability"] == "compose.release"
    assert effect["args"] == {
        "project_dir": "/srv/api",
        "service": "api",
        "image": "ghcr.io/acme/api:0123456789abcdef0123456789abcdef01234567",
    }


def test_missing_configuration_means_no_intent(monkeypatch):
    _configure(
        monkeypatch,
        release_project_dir="",
        release_service="",
        release_image_template="",
    )

    assert build_release_intent(PAYLOAD) is None
    assert missing_release_config() == [
        "RELEASE_PROJECT_DIR",
        "RELEASE_SERVICE",
        "RELEASE_IMAGE_TEMPLATE",
    ]


def test_unknown_placeholder_is_a_report_not_a_crash(monkeypatch):
    _configure(
        monkeypatch,
        release_project_dir="/srv/api",
        release_service="api",
        release_image_template="ghcr.io/{repo}:{commit}",
    )

    assert build_release_intent(PAYLOAD) is None
    assert "不认识的占位符" in release_skip_reason(PAYLOAD)


def test_other_base_branch_is_not_a_release(monkeypatch):
    _configure(
        monkeypatch,
        release_project_dir="/srv/api",
        release_service="api",
        release_image_template="ghcr.io/{repo}:{sha}",
        release_base_branch="production",
    )

    assert build_release_intent({**PAYLOAD, "base_ref": "main"}) is None


def test_default_binding_is_local(monkeypatch):
    _configure(monkeypatch, release_binding="")

    assert release_config()["binding"] == "local"


def _stub_workflow_steps(monkeypatch, seen: list):
    from engine.workflows import release as release_module

    async def open_step(payload):
        seen.append(("open", payload["issue_number"]))

    async def close_step(payload, report):
        seen.append(("close", report))

    async def apply_step(intent, payload, binding):
        seen.append(("apply", binding))
        return {
            "summary": intent["summary"],
            "applied": [{"capability": "compose.release", "verdict": "kept"}],
        }

    async def reply_step(payload, report, binding="github"):
        seen.append(("reply", payload["issue_number"], binding))

    monkeypatch.setattr(release_module, "_can_reply", lambda payload: True)
    monkeypatch.setattr(release_module, "open_incident_step", open_step)
    monkeypatch.setattr(release_module, "close_incident_step", close_step)
    monkeypatch.setattr(release_module, "apply_effects_on_binding_step", apply_step)
    monkeypatch.setattr(release_module, "reply_on_topic_step", reply_step)


def test_reply_is_skipped_without_a_comment_provider_for_the_source():
    from engine.workflows.release import _can_reply

    # 注册表里没有 GitLab 的 comment.create:不回,而不是拿 GitHub 去回。
    assert _can_reply({"source_adapter": "gitlab", "tenant_slug": "default"}) is False


def test_workflow_applies_release_on_configured_binding(monkeypatch):
    from engine.workflows import release as release_module

    _configure(
        monkeypatch,
        release_project_dir="/srv/api",
        release_service="api",
        release_image_template="ghcr.io/{repo}:{sha}",
        release_binding="prod-compose",
    )
    seen: list = []
    _stub_workflow_steps(monkeypatch, seen)

    report = asyncio.run(release_module._release_impl(PAYLOAD))

    assert ("apply", "prod-compose") in seen
    assert ("reply", 42, "github") in seen
    assert report["counts"] == {"kept": 1}


def test_workflow_does_not_apply_when_configuration_is_missing(monkeypatch):
    from engine.workflows import release as release_module

    _configure(
        monkeypatch,
        release_project_dir="",
        release_service="",
        release_image_template="",
    )
    seen: list = []
    _stub_workflow_steps(monkeypatch, seen)

    report = asyncio.run(release_module._release_impl(PAYLOAD))

    assert not any(item[0] == "apply" for item in seen)
    assert not any(item[0] == "reply" for item in seen)
    assert "未配置" in report["summary"]


class TestPullRequestWebhook:
    def _client(self, monkeypatch, merged: bool, captured: list):
        from engine.api.routes import webhook as webhook_mod
        from engine.ingest.events import event as normalized_event

        class Adapter:
            def webhook_configured(self):
                return True

            def verify_webhook(self, headers, body):
                return True

            def parse_webhook(self, headers, body):
                if not merged:
                    return None
                return normalized_event(
                    kind="merge",
                    source="github",
                    repo="acme/api",
                    repo_id=9,
                    change_id=77,
                    number=42,
                    title="修复空指针",
                    body="修好了",
                    base_ref="main",
                    head_ref="gwei/fix-1",
                    merge_sha=PAYLOAD["merge_sha"],
                )

        async def dedup(*args, **kwargs):
            return True

        async def enqueue(prefix, workflow, delivery_id, payload):
            captured.append((prefix, workflow.__name__, payload))
            return {"status": "queued"}

        monkeypatch.setattr(webhook_mod, "source_adapter", lambda source: Adapter())
        monkeypatch.setattr(webhook_mod, "dedup_once", dedup)
        monkeypatch.setattr(webhook_mod, "_enqueue_workflow", enqueue)

        app = FastAPI()
        app.include_router(webhook_mod.router)
        return TestClient(app)

    def test_merged_pull_request_queues_release(self, monkeypatch):
        captured: list = []
        client = self._client(monkeypatch, merged=True, captured=captured)

        resp = client.post(
            "/webhook/github",
            content=json.dumps(RAW),
            headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "d-1"},
        )

        assert resp.status_code == 200
        assert len(captured) == 1
        prefix, workflow_name, payload = captured[0]
        assert prefix == "gwei-release"
        assert workflow_name == "release_workflow"
        assert payload["merge_sha"] == PAYLOAD["merge_sha"]
        assert payload["base_ref"] == "main"

    def test_closed_without_merge_is_ignored(self, monkeypatch):
        captured: list = []
        client = self._client(monkeypatch, merged=False, captured=captured)

        resp = client.post(
            "/webhook/github",
            content=json.dumps(RAW),
            headers={"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "d-2"},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"
        assert captured == []
