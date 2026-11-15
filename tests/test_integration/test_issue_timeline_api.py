# tests/test_integration/test_issue_timeline_api.py
"""议题时间线接口 —— 需要 GWEI_TEST_DATABASE_URL(真实 Postgres)。

聚合本身在 test_issue_timeline 里用纯字典测过。这一层验的是取数:议题与它的
执行、事故、账本行对得上,而且**没有变更时也返回**(不是 404)。
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

requires_postgres = pytest.mark.skipif(
    not os.environ.get("GWEI_TEST_DATABASE_URL"),
    reason="需要 GWEI_TEST_DATABASE_URL 指向可写的 Postgres",
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import sqlalchemy as sa
    from fastapi.testclient import TestClient

    import engine.db.models  # noqa: F401 — 注册全部模型
    from engine.api.app import app
    from engine.db.base import Base
    from engine.shared.config import config

    # 账本与事故走文件:这一层验的是接线,不是账本后端。
    monkeypatch.setattr(config.settings, "change_ledger_backend", "file")
    monkeypatch.setattr(config.settings, "change_ledger_path", str(tmp_path / "ledger.jsonl"))

    # 自足建表:测试顺序不是契约。
    sync = sa.create_engine(os.environ["GWEI_TEST_DATABASE_URL"])
    with sync.connect() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(sync)
    sync.dispose()

    return TestClient(app)


def _seed_issue(title: str = "打开就崩") -> tuple[str, str]:
    """一个真实议题:租户、仓库、issue 三行落库。返回 (issue id, 租户 slug)。

    用同步 psycopg 写,不走 engine.db 的异步引擎:TestClient 在自己的事件循环里跑
    应用,先在 asyncio.run 里用它,连接池会把绑在已关闭循环上的 socket 交回来。
    """
    import sqlalchemy as sa
    from sqlalchemy.orm import Session

    from engine.db.models import Issue, Project, Tenant

    engine = sa.create_engine(os.environ["GWEI_TEST_DATABASE_URL"])
    try:
        with Session(engine) as db:
            tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="测试租户")
            db.add(tenant)
            db.flush()
            project = Project(
                tenant_id=tenant.id,
                github_id=uuid.uuid4().int % 10**9,
                name="acme/web",
            )
            db.add(project)
            db.flush()
            issue = Issue(
                github_id=uuid.uuid4().int % 10**9,
                project_id=project.id,
                number=7,
                title=title,
                body="点开就 500",
                labels=["bug"],
                status="OPEN",
            )
            db.add(issue)
            db.flush()
            ids = (str(issue.id), tenant.slug)
            db.commit()
            return ids
    finally:
        engine.dispose()


def _append_unit(topic: str, tenant: str, verdict: str = "kept") -> str:
    from engine.change_unit import ChangeUnit, Effect, JsonlLedger, Window
    from engine.shared.config import config

    unit = ChangeUnit(
        intent={
            "version": 1,
            "summary": "回评说明连接池要调大",
            "rationale": "问题在配置,不在代码",
            "evidence": [{"kind": "issue", "ref": topic}],
            "effects": [{"capability": "comment.create", "args": {"body": "hi"}}],
            "topic": topic,
            "workflow": "wf-1:effects",
        },
        effect=Effect(
            task="create_comment",
            args={"repo": "acme/web", "issue_number": 7, "body": "hi"},
            undo_task="delete_comment",
            undo_kind="symmetric",
            label="在 Issue / PR 上发一条评论",
            capability="comment.create",
        ),
        tenant=tenant,
        binding="github",
        incident_id="wf-1",
        handle="100" if verdict == "kept" else None,
        window=Window(unbounded=True, source="comment_present"),
        verdict=verdict,
        reason="验证通过,保持运行" if verdict == "kept" else "不在自动收敛范围,等你放行",
        facts={"found": True},
    )
    asyncio.run(JsonlLedger(config.settings.change_ledger_path).append(unit))
    return unit.id


@requires_postgres
class TestIssueTimeline:
    def test_an_issue_without_changes_still_returns(self, client):
        issue_id, _ = _seed_issue()
        resp = client.get(f"/api/issues/{issue_id}/timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert data["rounds"] == []
        assert data["state"] == "waiting"
        assert data["topic"] == "acme/web#7"

    def test_a_change_shows_up_on_the_line(self, client):
        issue_id, tenant = _seed_issue()
        _append_unit("acme/web#7", tenant)

        data = client.get(f"/api/issues/{issue_id}/timeline").json()
        assert data["state"] == "landed"
        assert len(data["rounds"]) == 1

        segments = data["rounds"][0]["segments"]
        # 没有会话与事故,线就从意图开始:这一行账仍然是它自己的故事
        assert [s["kind"] for s in segments] == ["intent", "change", "verify", "conclusion"]
        assert segments[0]["detail"]["rationale"] == "问题在配置,不在代码"
        assert segments[-1]["detail"]["undoable"] is True

    def test_another_tenants_change_does_not_leak_in(self, client):
        issue_id, _ = _seed_issue()
        _append_unit("acme/web#7", "someone-else")

        data = client.get(f"/api/issues/{issue_id}/timeline").json()
        assert data["rounds"] == []

    def test_unknown_or_malformed_ids_are_404(self, client):
        assert client.get(f"/api/issues/{uuid.uuid4()}/timeline").status_code == 404
        assert client.get("/api/issues/not-a-uuid/timeline").status_code == 404
    def test_board_puts_a_settled_issue_in_landed(self, client):
        issue_id, tenant = _seed_issue()
        _append_unit("acme/web#7", tenant)

        data = client.get("/api/board").json()
        assert set(data["counts"]) == {"waiting", "running", "landed"}
        mine = next(c for c in data["items"] if c["id"] == issue_id)
        assert mine["state"] == "landed"
        assert mine["action"] == ""
        assert mine["undoable"] is True
        assert mine["rounds"] == 1

    def test_board_says_what_a_blocked_issue_is_waiting_for(self, client):
        issue_id, tenant = _seed_issue()
        unit_id = _append_unit("acme/web#7", tenant, verdict="blocked")

        data = client.get("/api/board").json()
        mine = next(c for c in data["items"] if c["id"] == issue_id)
        assert mine["state"] == "waiting"
        assert mine["action"] == "approve"
        # 动作钉在那一条单元上,点进详情就能直接动手
        assert mine["unit_id"] == unit_id
        assert mine["waiting_since"]

    def test_board_is_ordered_waiting_first(self, client):
        _issue_id, tenant = _seed_issue()
        _append_unit("acme/web#7", tenant, verdict="blocked")

        data = client.get("/api/board").json()
        states = [c["state"] for c in data["items"]]
        assert states == sorted(states, key=lambda s: ["waiting", "running", "landed"].index(s))
    def test_continue_queues_the_same_workflow_on_the_same_topic(self, client):
        from unittest.mock import AsyncMock, patch

        import engine.api.routes.issues as issues_mod

        issue_id, _tenant = _seed_issue()
        queued = AsyncMock(return_value={"status": "queued", "workflow_id": "gwei-fix-abc"})
        with patch.object(issues_mod, "enqueue_workflow", queued):
            resp = client.post(
                f"/api/issues/{issue_id}/continue",
                json={"instruction": "把副本调到 6"},
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["workflow_id"] == "gwei-fix-abc"

        prefix, workflow, _delivery, payload = queued.call_args.args
        assert prefix == "gwei-fix"
        assert payload["topic"] == "acme/web#7"
        assert payload["signal"]["title"] == "把副本调到 6"
        # 议题自己的标题不能被这一轮改写
        assert payload["title"] == "打开就崩"

    def test_continue_rejects_a_blank_instruction(self, client):
        issue_id, _tenant = _seed_issue()
        resp = client.post(f"/api/issues/{issue_id}/continue", json={"instruction": "   "})
        assert resp.status_code == 422
