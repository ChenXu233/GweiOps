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
from engine.plugin_manager import hooks, registry
from engine.shared.cache import LLM_ANALYSIS_TTL_S, cached_json, cache_key
from engine.change_unit import ChangeUnit, apply as apply_change_unit, create_ledger
from engine.ingest import from_github
from engine.shared.config import config
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


def signal_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """监控载荷本身已经是一条归一化信号;GitHub 载荷是内联字段,现场翻译。"""
    inline = payload.get("signal")
    if isinstance(inline, dict) and inline.get("title"):
        return inline
    return from_github(payload)


async def _recent_conclusions(tenant: str, limit: int = 20) -> list[dict[str, Any]]:
    """这个租户最近的账本结论,给 intent 提供者当证据。

    读不到就是读不到:空列表表示"没有证据",不表示"一直很顺"。
    """
    try:
        rows = await create_ledger().latest(tenant=tenant, limit=limit)
    except Exception:
        logger.warning("账本读不到,这次提议不带履历", exc_info=True)
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        effect = row.get("effect")
        out.append(
            {
                "verdict": row.get("verdict", ""),
                "capability": effect.get("capability", "") if isinstance(effect, dict) else "",
                "binding": row.get("binding", ""),
                "reason": row.get("reason", ""),
            }
        )
    return out


async def _propose_intent_impl(payload: dict, analysis: dict, patches: list[dict]) -> dict:
    """经能力通道拿 intent;没有提供者时用现有结论兜底,工作流不因缺插件停摆。"""
    signal = signal_from_payload(payload)
    params: dict[str, Any] = {"signal": signal, "analysis": analysis, "patches": patches}
    # 只有明确要证据的提供者才去读账本:没人读的时候,这个读只是把库的延迟加进工作流。
    provider = registry.best_capability_provider("intent.propose")
    if provider is not None and getattr(provider, "wants_history", False):
        history = await _recent_conclusions(payload.get("tenant_slug", ""))
        if history:
            params["history"] = history
    try:
        return await registry.run_capability("intent.propose", params)
    except LookupError:
        logger.info("No provider for intent.propose; falling back to local intent")

    if not payload.get("repo_full_name"):
        # 本地兜底只会把 GitHub issue 信号翻成一条回评。别的来源没有提供者就是没有动作,
        # 这里如实返回空 effects:编一个动作出来,比什么都不做更危险。
        return {
            "version": 1,
            "summary": f"信号「{signal['title']}」没有可执行的意图",
            "evidence": [{"kind": signal["source"], "ref": signal["subject"]}],
            "effects": [],
            "rationale": "没有 intent 提供者能处理这个来源;本地兜底只处理 GitHub issue。",
        }

    body = _format_suggestion_reply(payload, patches) if patches else analysis.get("reply")
    effects = []
    if body:
        effects.append(
            {
                "capability": "comment.create",
                "args": {
                    "repo": payload["repo_full_name"],
                    "issue_number": payload["issue_number"],
                    "body": body,
                },
            }
        )
    return {
        "version": 1,
        "summary": f"针对 {payload['title']} 的 {len(patches)} 个候选补丁" if patches else "回评",
        "evidence": [
            {"kind": "issue", "ref": f"{payload['repo_full_name']}#{payload['issue_number']}"}
        ],
        "effects": effects,
        "rationale": "本地兜底:没有 intent 提供者时把既有结论转成效果。",
    }


async def _apply_effects_impl(intent: dict, payload: dict, idem_base: str) -> dict:
    """把 intent 里的候选效果逐个落成变更单元:解析提供者 → 执行 → 验证 → 记账。"""
    from engine.change_unit.intent import parse_intent

    parsed = parse_intent(intent)
    tenant = payload.get("tenant_slug", "")
    binding = config.settings.default_binding
    ledger = create_ledger()

    applied: list[dict] = []
    for index, effect in enumerate(parsed.effects):
        capability = effect["capability"]
        args = dict(effect.get("args") or {})

        if capability == "comment.create" and payload.get("repo_full_name"):
            gated = await hooks.apply(
                "comment.posting",
                {
                    "tenant_slug": tenant,
                    "repo_full_name": payload["repo_full_name"],
                    "issue_number": payload["issue_number"],
                    "body": args.get("body", ""),
                },
            )
            if not gated["allowed"]:
                applied.append({"capability": capability, "verdict": "vetoed"})
                continue
            args["body"] = gated["payload"]["body"]

        try:
            provider, decl = registry.effect_decl(capability, tenant=tenant, binding=binding)
        except LookupError as e:
            # intent 点了一个没人提供的能力(比如告警声明的动作还没装):
            # 记成阻断,不让整个工作流因为一个效果崩掉。
            applied.append(
                {
                    "capability": capability,
                    "verdict": "blocked",
                    "handle": None,
                    "reason": f"没有提供者声明这个能力: {e}",
                }
            )
            continue

        unit = ChangeUnit(
            intent={"workflow": idem_base, "summary": parsed.summary},
            effect=decl.to_effect(args),
            tenant=tenant,
            binding=binding,
            idempotency_key=f"{idem_base}:effect:{index}",
        )
        outcome = await apply_change_unit(unit, provider, ledger)
        applied.append(
            {
                "capability": capability,
                "verdict": outcome.verdict,
                "handle": outcome.handle,
                "reason": outcome.reason,
            }
        )

    return {"summary": parsed.summary, "applied": applied}


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
async def apply_hooks_step(point: str, payload: dict) -> dict:
    """Hook 管线以 step 封装获得 checkpoint,返回 {"allowed", "payload"}。"""
    return await hooks.apply(point, payload)


@DBOS.step()
async def propose_intent_step(payload: dict, analysis: dict, patches: list) -> dict:
    return await _propose_intent_impl(payload, analysis, patches)


@DBOS.step()
async def apply_effects_step(intent: dict, payload: dict) -> dict:
    """效果执行以 workflow_id 作为幂等基座:重放只复用账本结论。"""
    return await _apply_effects_impl(intent, payload, f"{DBOS.workflow_id}:effects")


@DBOS.step()
async def propose_alert_intent_step(payload: dict) -> dict:
    return await _propose_intent_impl(payload, {}, [])


@DBOS.workflow()
async def alert_triage_workflow(payload: dict) -> dict:
    """监控信号:没有补丁、没有回评,只有意图与效果。

    信号本身不携带动作。能做什么由 intent 提供者决定;没有提供者时
    effects 为空,工作流正常结束——不假装做了什么。
    """
    intent = await propose_alert_intent_step(payload)
    applied = await apply_effects_step(intent, payload)

    return {
        "signal": (payload.get("signal") or {}).get("subject", ""),
        "intent": intent.get("summary", ""),
        "applied": applied,
    }


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
    intent = await propose_intent_step(payload, analysis, [])
    applied = await apply_effects_step(intent, payload)

    return {
        "record": record,
        "intent": intent.get("summary", ""),
        "applied": applied,
    }


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

    intent = await propose_intent_step(payload, analysis, patches)
    applied = await apply_effects_step(intent, payload)

    return {
        "record": record,
        "patch_count": len(patches),
        "intent": intent.get("summary", ""),
        "applied": applied,
    }
