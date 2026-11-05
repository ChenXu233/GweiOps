# tests/test_integration/test_console.py
"""控制台只读 API 测试 —— 需要 GWEI_TEST_DATABASE_URL(真实 Postgres)。"""

import os
import uuid

import pytest

requires_postgres = pytest.mark.skipif(
    not os.environ.get("GWEI_TEST_DATABASE_URL"),
    reason="需要 GWEI_TEST_DATABASE_URL 指向可写的 Postgres",
)


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from engine.api.app import app
    from engine.plugin_manager import registry

    if not registry.names():
        registry.discover()
    return TestClient(app)


@requires_postgres
class TestConsole:
    def test_dashboard_shape(self, client):
        resp = client.get("/api/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("status", "pendingReview", "overnightFixed", "activeAgents", "successRate"):
            assert key in data
        assert data["activeAgents"] >= 1

    def test_issues_empty_then_shape(self, client):
        resp = client.get("/api/issues")
        assert resp.status_code == 200
        # 无数据时为空列表;有数据时形状完整
        for issue in resp.json():
            assert {"id", "title", "severity", "status", "repo", "patches", "timeline"} <= set(issue)

    def test_issue_detail_404(self, client):
        resp = client.get(f"/api/issues/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_repos_and_settings(self, client):
        repos = client.get("/api/repos").json()
        for repo in repos:
            assert {"id", "name", "issueCount", "status"} <= set(repo)

        settings = client.get("/api/settings").json()
        assert settings["plan"] == "selfhost"

    def test_canary_honest_empty(self, client):
        assert client.get("/api/dashboard/canary").json() == []

    def test_runs_shape(self, client):
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert {"items", "total"} <= set(data)
        for run in data["items"]:
            assert {
                "id",
                "issueId",
                "issueTitle",
                "repo",
                "status",
                "source",
                "startedAt",
                "endedAt",
                "durationMs",
            } <= set(run)
            # 会话没结束时耗时如实留空,不拿 0 顶替
            if run["endedAt"] is None:
                assert run["durationMs"] is None
