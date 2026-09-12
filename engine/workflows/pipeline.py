# engine/workflows/pipeline.py
"""GweiOps 工作流管道 — DBOS 持久化执行。

两个入口工作流：
- issue_triage_workflow:  issues opened/edited → Sensor 感知分析 → 落库 → 回评
- fix_suggestion_workflow: @gwei 评论 → 落库 → Fixer 补丁建议 → 格式化 → 回评

约定：
- 每个步骤一个 @DBOS.step()，纯逻辑抽成同名 `_impl` 普通函数便于单测；
- 步骤输入输出必须是 JSON 可序列化 dict；
- 持久化执行状态由 DBOS 写入 Postgres（dbos schema），业务数据写业务表；
- 回评失败不使工作流失败（分析已落库，评论可由 GitHub 重投递补偿）。
"""

import logging
from typing import Any

from sqlalchemy import select

from dbos import DBOS

from engine.db import async_session_factory
from engine.db.models import AgentSession, Issue, Project
from engine.shared.cache import LLM_ANALYSIS_TTL_S, cached_json, cache_key
from engine.shared.runtime import get_adapter, get_sensor

logger = logging.getLogger(__name__)

WORKFLOW_QUEUE = "gwei-agents"


# ---------------------------------------------------------------------------
# 步骤实现（纯逻辑，可脱离 DBOS 直接单测）
# ---------------------------------------------------------------------------


async def _analyze_via_sensor(payload: dict) -> dict:
    """调用 Sensor 智能体做感知分析（规则 + LLM）。"""
    sensor = get_sensor()
    return await sensor.handle_event(
        "issue.created",
        {"issue": {"title": payload["title"], "body": payload["body"]}},
    )


async def _analyze_with_cache(payload: dict) -> dict:
    """感知分析 + Redis 结果缓存（内容哈希键，内容未变不重调 LLM）。"""
    key = cache_key("llm-analysis", payload["title"], payload["body"])
    return await cached_json(key, LLM_ANALYSIS_TTL_S, lambda: _analyze_via_sensor(payload))


async def _persist_triage_impl(payload: dict, analysis: dict, status: str) -> dict:
    """按 GitHub ID 幂等 upsert Project/Issue，并新建 AgentSession 记录本次运行。"""
    async with async_session_factory() as session:
        try:
            project = (
                await session.execute(
                    select(Project).where(Project.github_id == payload["repo_github_id"])
                )
            ).scalar_one_or_none()
            if project is None:
                project = Project(
                    github_id=payload["repo_github_id"],
                    name=payload["repo_full_name"],
                )
                session.add(project)
                await session.flush()

            issue = (
                await session.execute(
                    select(Issue).where(Issue.github_id == payload["issue_github_id"])
                )
            ).scalar_one_or_none()
            if issue is None:
                issue = Issue(
                    github_id=payload["issue_github_id"],
                    project_id=project.id,
                    number=payload["issue_number"],
                    title=payload["title"],
                    body=payload["body"],
                    labels=analysis.get("labels"),
                    status="OPEN",
                )
                session.add(issue)
            else:
                issue.title = payload["title"]
                issue.body = payload["body"]
                issue.labels = analysis.get("labels")
            await session.flush()

            agent_session = AgentSession(
                issue_id=issue.id,
                status=status,
                state={
                    "workflow_id": DBOS.workflow_id,
                    "source": payload.get("source"),
                    "analysis": {
                        "labels": analysis.get("labels"),
                        "is_complete": analysis.get("is_complete"),
                        "completeness_score": analysis.get("completeness_score"),
                        "llm_analysis": analysis.get("llm_analysis"),
                    },
                },
            )
            session.add(agent_session)
            await session.commit()
            return {
                "project_id": str(project.id),
                "issue_id": str(issue.id),
                "session_id": str(agent_session.id),
            }
        except Exception:
            await session.rollback()
            raise


async def _generate_patches_impl(payload: dict) -> list[dict]:
    """调用 Fixer 智能体生成候选补丁建议。"""
    from plugins.builtin.agents.fixer.plugin import FixerAgent

    fixer = FixerAgent()
    result = await fixer.execute_task(
        "generate_patches",
        {"title": payload["title"], "body": payload["body"], "file_path": ""},
    )
    return list(result.get("patches", []))


async def _post_comment_impl(payload: dict, body: str) -> dict:
    """通过 GitHub App 在 Issue 上回评。失败只记录，不使工作流失败。"""
    adapter = get_adapter()
    if adapter.config is None:
        await adapter.on_startup()
    try:
        await adapter.execute_task(
            "create_comment",
            {
                "repo": payload["repo_full_name"],
                "issue_number": payload["issue_number"],
                "body": body,
            },
        )
        return {"posted": True}
    except Exception as e:
        logger.error(
            "Failed to post comment on %s#%s: %s",
            payload["repo_full_name"],
            payload["issue_number"],
            e,
        )
        return {"posted": False, "error": str(e)}


def _format_suggestion_reply(payload: dict, patches: list[dict]) -> str:
    """把补丁建议格式化为 Issue 评论 Markdown（纯函数，保持确定性）。"""
    lines = [
        "## 🛠 GweiOps 修复建议",
        "",
        f"针对 **{payload['title']}** 生成了 {len(patches)} 个候选补丁（仅建议，未自动应用）：",
        "",
    ]
    for i, patch in enumerate(patches, 1):
        lines += [
            f"### 方案 {i} · {patch.get('type', 'PATCH')}（风险：{patch.get('risk', '未知')}）",
            "",
            patch.get("description", ""),
            "",
            "```diff",
            patch.get("diff", ""),
            "```",
            "",
        ]
    lines += ["---", "*由 GweiOps fixer 智能体生成；如需调整请回复 @gwei 并补充说明。*"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DBOS 步骤与工作流
# ---------------------------------------------------------------------------


@DBOS.step()
async def analyze_issue_step(payload: dict) -> dict:
    return await _analyze_with_cache(payload)


@DBOS.step()
async def persist_triage_step(payload: dict, analysis: dict, status: str) -> dict:
    return await _persist_triage_impl(payload, analysis, status)


@DBOS.step()
async def generate_patches_step(payload: dict) -> list[dict]:
    return await _generate_patches_impl(payload)


@DBOS.step()
async def post_comment_step(payload: dict, body: str) -> dict:
    return await _post_comment_impl(payload, body)


@DBOS.workflow()
async def issue_triage_workflow(payload: dict) -> dict:
    """Issue 感知工作流：分析 → 落库 → 回评。"""
    analysis: dict[str, Any] = await analyze_issue_step(payload)
    record = await persist_triage_step(payload, analysis, status="TRIAGED")

    posted: dict[str, Any] = {"posted": False}
    reply = analysis.get("reply")
    if reply:
        posted = await post_comment_step(payload, reply)

    return {"record": record, "posted": posted}


@DBOS.workflow()
async def fix_suggestion_workflow(payload: dict) -> dict:
    """@gwei 修复建议工作流：落库 → 补丁建议 → 格式化 → 回评（不自动建 PR）。"""
    analysis = await analyze_issue_step(payload)
    record = await persist_triage_step(payload, analysis, status="FIX_REQUESTED")

    patches = await generate_patches_step(payload)
    reply = _format_suggestion_reply(payload, patches)
    posted = await post_comment_step(payload, reply)

    return {"record": record, "patch_count": len(patches), "posted": posted}
