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
from engine.db.models import AgentSession, Issue, Project, Tenant
from engine.plugin_manager import events, hooks, registry
from engine.shared.cache import LLM_ANALYSIS_TTL_S, cached_json, cache_key
from engine.shared.render import format_suggestion_reply as _format_suggestion_reply
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
    """感知分析 + Redis 结果缓存（内容哈希键，内容未变不重调 LLM）。

    LLM 调用失败时 sensor 会降级返回失败文案——这类结果不缓存，
    避免 24 小时内反复命中失败产物。
    """
    key = cache_key(
        "llm-analysis", payload.get("tenant_slug", ""), payload["title"], payload["body"]
    )
    return await cached_json(
        key,
        LLM_ANALYSIS_TTL_S,
        lambda: _analyze_via_sensor(payload),
        cacheable=lambda r: "LLM 分析失败" not in str(r.get("llm_analysis", "")),
    )


async def _persist_triage_impl(payload: dict, analysis: dict, status: str) -> dict:
    """按租户与 GitHub ID 幂等 upsert Tenant/Project/Issue,并新建 AgentSession。"""
    async with async_session_factory() as session:
        try:
            tenant = (
                await session.execute(select(Tenant).where(Tenant.slug == payload["tenant_slug"]))
            ).scalar_one_or_none()
            if tenant is None:
                tenant = Tenant(slug=payload["tenant_slug"], name=payload["tenant_slug"])
                session.add(tenant)
                await session.flush()

            project = (
                await session.execute(
                    select(Project).where(
                        Project.tenant_id == tenant.id,
                        Project.github_id == payload["repo_github_id"],
                    )
                )
            ).scalar_one_or_none()
            if project is None:
                project = Project(
                    tenant_id=tenant.id,
                    github_id=payload["repo_github_id"],
                    name=payload["repo_full_name"],
                )
                session.add(project)
                await session.flush()

            issue = (
                await session.execute(
                    select(Issue).where(
                        Issue.project_id == project.id,
                        Issue.github_id == payload["issue_github_id"],
                    )
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
                    "tenant_id": str(tenant.id),
                    "source": payload.get("source"),
                    "analysis": {
                        "labels": analysis.get("labels"),
                        "is_complete": analysis.get("is_complete"),
                        "completeness_score": analysis.get("completeness_score"),
                        "llm_analysis": analysis.get("llm_analysis"),
                        "llm_tokens": analysis.get("llm_tokens", 0),
                    },
                },
            )
            session.add(agent_session)
            await session.commit()
            return {
                "tenant_id": str(tenant.id),
                "project_id": str(project.id),
                "issue_id": str(issue.id),
                "session_id": str(agent_session.id),
            }
        except Exception:
            await session.rollback()
            raise


async def _generate_patches_impl(payload: dict) -> list[dict]:
    """经能力通道调用修复智能体;注册表不可用时回退直连(单测与降级路径)。"""
    try:
        result = await registry.run_capability("patch.generate", {
            "title": payload["title"],
            "body": payload["body"],
            "file_path": "",
        })
        return list(result.get("patches", []))
    except LookupError:
        logger.info("No provider for patch.generate; falling back to direct FixerAgent")
    except Exception as e:
        logger.warning("Capability patch.generate failed, falling back: %s", e)

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


@DBOS.step()
async def publish_event_step(event: str, payload: dict) -> bool:
    """事件以 step 封装获得 checkpoint——恢复重放不会重复发布。"""
    await events.publish(event, payload)
    return True


@DBOS.step()
async def apply_hooks_step(point: str, payload: dict) -> dict:
    """Hook 管线以 step 封装获得 checkpoint,返回 {"allowed", "payload"}。"""
    return await hooks.apply(point, payload)


@DBOS.workflow()
async def issue_triage_workflow(payload: dict) -> dict:
    """Issue 感知工作流：分析 → 落库 → Hook 观察点 → 事件链 → 回评。"""
    analysis: dict[str, Any] = await analyze_issue_step(payload)
    record = await persist_triage_step(payload, analysis, status="TRIAGED")

    hooked = await apply_hooks_step("issue.triaged", {
        "tenant_slug": payload["tenant_slug"],
        "repo_full_name": payload["repo_full_name"],
        "issue": {"title": payload["title"], "body": payload["body"]},
        "analysis": analysis,
    })
    hooked_payload = hooked["payload"]

    # 保守事件链:diagnoser 经 manifest 订阅 sensor.processed 自动触发
    await publish_event_step("sensor.processed", hooked_payload)

    posted: dict[str, Any] = {"posted": False}
    reply = analysis.get("reply")
    if reply:
        gated = await apply_hooks_step("comment.posting", {
            "tenant_slug": payload["tenant_slug"],
            "repo_full_name": payload["repo_full_name"],
            "issue_number": payload["issue_number"],
            "body": reply,
        })
        if gated["allowed"]:
            posted = await post_comment_step(payload, gated["payload"]["body"])
        else:
            posted = {"posted": False, "vetoed": True}

    return {"record": record, "posted": posted}


@DBOS.workflow()
async def fix_suggestion_workflow(payload: dict) -> dict:
    """@gwei 修复建议工作流：落库 → 补丁建议 → Hook → 格式化 → 回评（不自动建 PR）。"""
    analysis = await analyze_issue_step(payload)
    record = await persist_triage_step(payload, analysis, status="FIX_REQUESTED")

    patches = await generate_patches_step(payload)
    hooked = await apply_hooks_step("patch.generated", {
        "tenant_slug": payload["tenant_slug"],
        "repo_full_name": payload["repo_full_name"],
        "patches": patches,
    })
    if hooked["allowed"]:
        patches = hooked["payload"]["patches"]

    reply = _format_suggestion_reply(payload, patches)
    gated = await apply_hooks_step("comment.posting", {
        "tenant_slug": payload["tenant_slug"],
        "repo_full_name": payload["repo_full_name"],
        "issue_number": payload["issue_number"],
        "body": reply,
    })

    posted: dict[str, Any] = {"posted": False}
    if gated["allowed"]:
        posted = await post_comment_step(payload, gated["payload"]["body"])
    else:
        posted = {"posted": False, "vetoed": True}

    return {"record": record, "patch_count": len(patches), "posted": posted}
