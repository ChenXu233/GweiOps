# tests/test_integration/test_pipeline.py
"""工作流管道测试。

默认只运行无需外部服务的部分：步骤纯逻辑实现、payload 提取、缓存/去重的
降级行为。需要真实 Postgres 的 DBOS 端到端测试通过 GWEI_TEST_DATABASE_URL
门控（例如指向 docker compose 启动的 gwei-postgres-dev）。
"""

import asyncio
import importlib
import json
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================================
# Redis 增益层：降级行为
# ============================================================================


class TestCache:
    def test_cache_key_stable(self):
        from engine.shared.cache import cache_key

        assert cache_key("a", "b") == cache_key("a", "b")
        assert cache_key("a", "b") != cache_key("b", "a")

    @pytest.mark.asyncio
    async def test_dedup_degrades_when_redis_down(self):
        import engine.shared.cache as cache_mod

        with patch.object(cache_mod, "_get_client", side_effect=Exception("redis down")):
            assert await cache_mod.dedup_once("k", 60) is True

    @pytest.mark.asyncio
    async def test_cached_json_executes_factory_when_redis_down(self):
        import engine.shared.cache as cache_mod

        with patch.object(cache_mod, "_get_client", side_effect=Exception("redis down")):
            calls = []

            async def factory():
                calls.append(1)
                return {"v": 1}

            assert await cache_mod.cached_json("k", 60, factory) == {"v": 1}
            assert len(calls) == 1


# ============================================================================
# Webhook payload 提取
# ============================================================================


class TestPayloadExtraction:
    @staticmethod
    def _issue_info():
        return {"owner": "my-org", "repo": "my-repo", "issue_number": 42, "title": "Bug"}

    def test_extract_issue_payload(self):
        from engine.api.routes.webhook import _extract_payload

        raw = {
            "repository": {"id": 1},
            "issue": {"id": 100, "title": "Bug", "body": "B"},
        }
        payload = _extract_payload(raw, self._issue_info(), "issues")

        assert payload is not None
        assert payload["repo_github_id"] == 1
        assert payload["issue_github_id"] == 100
        assert payload["repo_full_name"] == "my-org/my-repo"
        assert payload["issue_number"] == 42
        assert payload["source"] == "issue"

    def test_extract_comment_payload_uses_comment_body(self):
        from engine.api.routes.webhook import _extract_payload

        raw = {
            "repository": {"id": 1},
            "issue": {"id": 100, "title": "Bug"},
            "comment": {"body": "@gwei 请修复"},
        }
        payload = _extract_payload(raw, self._issue_info(), "issue_comment")

        assert payload is not None
        assert payload["body"] == "@gwei 请修复"
        assert payload["source"] == "comment"

    def test_missing_ids_returns_none(self):
        from engine.api.routes.webhook import _extract_payload

        raw = {"repository": {}, "issue": {}}
        assert _extract_payload(raw, self._issue_info(), "issues") is None


# ============================================================================
# 工作流步骤纯逻辑实现
# ============================================================================


class TestPipelineImpls:
    def test_format_suggestion_reply(self):
        from engine.workflows.pipeline import _format_suggestion_reply

        payload = {"repo_full_name": "my-org/my-repo", "issue_number": 7, "title": "Bug"}
        patches = [
            {
                "type": "HOTFIX",
                "diff": "--- a/x.py\n+++ b/x.py",
                "risk": "Low",
                "description": "最小修复",
            }
        ]
        reply = _format_suggestion_reply(payload, patches)

        assert "```diff" in reply
        assert "--- a/x.py" in reply
        assert "HOTFIX" in reply
        assert "未自动应用" in reply

    @pytest.mark.asyncio
    async def test_analyze_via_sensor(self):
        from engine.workflows.pipeline import _analyze_via_sensor

        with patch("engine.workflows.pipeline.get_sensor") as mock_get_sensor:
            sensor = MagicMock()
            sensor.handle_event = AsyncMock(
                return_value={"status": "ok", "reply": "r", "labels": ["bug"]}
            )
            mock_get_sensor.return_value = sensor

            result = await _analyze_via_sensor({"title": "T", "body": "B"})

        assert result["reply"] == "r"
        sensor.handle_event.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_analyze_with_cache_goes_through_cached_json(self):
        from engine.workflows.pipeline import _analyze_with_cache

        cached = AsyncMock(return_value={"status": "ok"})
        with patch("engine.workflows.pipeline.cached_json", cached):
            result = await _analyze_with_cache({"title": "T", "body": "B"})

        assert result == {"status": "ok"}
        cached.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_generate_patches_impl(self):
        from engine.workflows.pipeline import _generate_patches_impl

        with patch("plugins.builtin.agents.fixer.plugin.FixerAgent") as mock_fixer_cls:
            fixer = mock_fixer_cls.return_value
            fixer.execute_task = AsyncMock(
                return_value={
                    "patches": [
                        {"type": "HOTFIX", "diff": "d", "risk": "Low", "description": "x"}
                    ]
                }
            )

            patches = await _generate_patches_impl({"title": "T", "body": "B"})

        assert len(patches) == 1
        assert patches[0]["type"] == "HOTFIX"
        fixer.execute_task.assert_awaited_once_with(
            "generate_patches", {"title": "T", "body": "B", "file_path": ""}
        )

    @pytest.mark.asyncio
    async def test_post_comment_impl_swallows_failure(self):
        from engine.workflows.pipeline import _post_comment_impl

        with patch("engine.workflows.pipeline.get_adapter") as mock_get_adapter:
            adapter = MagicMock()
            adapter.config = MagicMock()  # 非空则跳过 on_startup
            adapter.execute_task = AsyncMock(side_effect=Exception("gh down"))
            mock_get_adapter.return_value = adapter

            result = await _post_comment_impl(
                {"repo_full_name": "my-org/my-repo", "issue_number": 1}, "hi"
            )

        assert result["posted"] is False
        assert "gh down" in result["error"]


# ============================================================================
# 工作流符号与导出（无需启动 DBOS）
# ============================================================================


class TestWorkflowSymbols:
    def test_pipeline_exports(self):
        import engine.workflows.pipeline as pipeline

        assert pipeline.WORKFLOW_QUEUE == "gwei-agents"
        assert callable(pipeline.issue_triage_workflow)
        assert callable(pipeline.fix_suggestion_workflow)

    def test_package_reexports(self):
        from engine.workflows import (
            WORKFLOW_QUEUE,
            fix_suggestion_workflow,
            issue_triage_workflow,
        )

        assert WORKFLOW_QUEUE == "gwei-agents"


# ============================================================================
# DBOS 端到端（需要真实 Postgres，通过环境变量门控）
# ============================================================================


def _postgres_url() -> str:
    return os.environ["GWEI_TEST_DATABASE_URL"]


requires_postgres = pytest.mark.skipif(
    not os.environ.get("GWEI_TEST_DATABASE_URL"),
    reason="需要 GWEI_TEST_DATABASE_URL 指向可写的 Postgres",
)


class _FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


def _make_fake_session_factory():
    """模拟业务库会话：首次查询返回 None（走创建路径），记录 add/commit 调用。"""
    added = []

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        execute = AsyncMock(return_value=_FakeResult(None))
        flush = AsyncMock()
        commit = AsyncMock()
        rollback = AsyncMock()

        @staticmethod
        def add(obj):
            added.append(obj)

    session = _FakeSession()
    # flush 后对象获得主键（模拟数据库默认值）
    async def _flush():
        for obj in added:
            if not hasattr(obj, "id") or obj.id is None:
                obj.id = uuid.uuid4()

    session.flush = AsyncMock(side_effect=_flush)
    return session, added


@requires_postgres
class TestWorkflowEndToEnd:
    @pytest.mark.asyncio
    async def test_triage_workflow_idempotent(self):
        """端到端：入队 → 执行 → 幂等重入队只执行一次。"""
        import engine.workflows.pipeline as pipeline_module
        from dbos import DBOS, DBOSConfig, SetWorkflowID

        # 隔离测试环境：销毁默认 DBOS 实例，用测试库重建
        DBOS.destroy(destroy_registry=True)
        importlib.reload(pipeline_module)

        try:
            DBOS(
                config=DBOSConfig(
                    name="gwei-test",
                    system_database_url=_postgres_url(),
                )
            )
            DBOS.launch()
            await DBOS.register_queue_async("gwei-test-queue", worker_concurrency=2)

            session, added = _make_fake_session_factory()

            with patch.object(pipeline_module, "get_sensor") as mock_get_sensor, patch.object(
                pipeline_module, "get_adapter"
            ) as mock_get_adapter, patch.object(
                pipeline_module, "async_session_factory", return_value=session
            ):
                sensor = MagicMock()
                sensor.handle_event = AsyncMock(
                    return_value={
                        "status": "ok",
                        "reply": "分析完成",
                        "labels": ["bug"],
                        "is_complete": True,
                        "completeness_score": 1.0,
                    }
                )
                mock_get_sensor.return_value = sensor

                adapter = MagicMock()
                adapter.config = MagicMock()
                adapter.execute_task = AsyncMock(return_value={"success": True})
                mock_get_adapter.return_value = adapter

                payload = {
                    "tenant_slug": "default",
                    "repo_full_name": "my-org/my-repo",
                    "repo_github_id": 1,
                    "issue_github_id": 100,
                    "issue_number": 7,
                    "title": "Test Bug",
                    "body": "Steps to reproduce...",
                    "source": "issue",
                }

                workflow_id = f"gwei-triage-{uuid.uuid4()}"
                with SetWorkflowID(workflow_id):
                    await DBOS.enqueue_workflow_async(
                        "gwei-test-queue", pipeline_module.issue_triage_workflow, payload
                    )
                # 幂等：同 ID 重复入队不产生第二次执行
                with SetWorkflowID(workflow_id):
                    await DBOS.enqueue_workflow_async(
                        "gwei-test-queue", pipeline_module.issue_triage_workflow, payload
                    )

                result = await asyncio.wait_for(
                    DBOS.get_result_async(workflow_id), timeout=60
                )

                assert result["posted"]["posted"] is True
                assert result["record"]["tenant_id"]
                assert len(added) == 4  # Tenant + Project + Issue + AgentSession
                sensor.handle_event.assert_awaited_once()
                adapter.execute_task.assert_awaited_once()
        finally:
            DBOS.destroy(destroy_registry=True)
