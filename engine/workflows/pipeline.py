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
from pathlib import Path
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


async def _apply_effects_impl(
    intent: dict, payload: dict, idem_base: str, incident_id: str = ""
) -> dict:
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
            incident_id=incident_id,
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
    return await _apply_effects_impl(
        intent, payload, f"{DBOS.workflow_id}:effects", incident_id=DBOS.workflow_id
    )


async def _handle_incident_impl(payload: dict) -> dict | None:
    """有 agent 提供者就让它整场处理;没有就返回 None,走原来的声明式路径。

    两条路落在同一本账上:agent 每动一次世界,都是一个变更单元。
    """
    if registry.best_capability_provider("incident.handle") is None:
        return None
    signal = signal_from_payload(payload)
    return await registry.run_capability(
        "incident.handle",
        {
            "signal": signal,
            "incident_id": DBOS.workflow_id,
            "tenant": payload.get("tenant_slug", ""),
            "binding": config.settings.default_binding,
            "idem_base": f"{DBOS.workflow_id}:incident",
        },
    )


async def _thread_for(payload: dict) -> dict | None:
    """这个话题上接着要改的那个 PR。

    先看账本:同一个话题上开出来、此刻还开着的 PR 就是它。账本没有、而这次评论
    落在 PR 上,再问一次 GitHub —— 人自己开的 PR 也要能接着改。
    """
    topic = str(payload.get("topic") or "")
    if not topic:
        return None

    from engine.change_unit.threads import open_pull_on

    thread = await open_pull_on(create_ledger(), payload.get("tenant_slug", ""), topic)
    if thread is not None:
        return thread

    repo = payload.get("repo_full_name") or ""
    number = payload.get("issue_number")
    if not payload.get("is_pull") or not repo or number is None:
        return None
    try:
        adapter = get_adapter()
        if adapter.config is None:
            await adapter.on_startup()
        pull = await adapter.client.get_pull(repo, int(number))
    except Exception as exc:  # noqa: BLE001 - 问不到就当没有,不猜一个分支
        logger.info("could not read pull %s#%s: %s", repo, number, exc)
        return None
    head = ((pull or {}).get("head") or {}).get("ref") or ""
    if not head:
        return None
    return {
        "repo": repo,
        "head": head,
        "pull": str(number),
        "url": (pull or {}).get("html_url", ""),
    }


async def _prepare_workspace_impl(payload: dict) -> dict:
    """开工前把代码放进工作区:从哪拉、基线是哪条分支。

    凭据在这一步用掉一次,之后容器里就只有文件了。拉不到就如实返回,让工作流
    带着原因收尾——空工作区里跑一个 agent,只会得到一份看着像真的报告。
    """
    repo = payload.get("repo_full_name") or ""
    if not repo:
        return {}

    from engine.harness import workspace as ws

    adapter = get_adapter()
    if adapter.config is None:
        await adapter.on_startup()
    source = await adapter.workspace_source(repo)
    checkout = await ws.prepare(
        source=source,
        root=config.settings.harness_workspace_root,
        incident_id=DBOS.workflow_id,
    )
    return {"repo": repo, "branch": checkout.branch, "commit": checkout.commit}


def harness_configured() -> bool:
    """部署里配了 harness 吗。工作流据此决定开不开事故、走不走 agent。"""
    return bool((config.settings.harness_command or "").strip())


async def _run_harness_impl(payload: dict) -> dict | None:
    """有外部 harness 就交给它;没有就返回 None,往下回落到进程内或声明式。

    harness 在自己的工作区里跑,平台只负责交进去、收回来。它改世界仍然走出口,
    所以变更与账本跟进程内 agent 一模一样。
    """
    command = (config.settings.harness_command or "").strip()
    if not command:
        return None

    from engine.harness import build_task, run_harness

    incident_id = DBOS.workflow_id
    workspace = Path(config.settings.harness_workspace_root) / incident_id
    exit_url = config.settings.platform_base_url.rstrip("/") + "/api/agent/exits"

    repo = payload.get("repo_full_name") or ""
    branch = ""
    if repo:
        try:
            prepared = await _prepare_workspace_impl(payload)
            branch = prepared.get("branch", "")
        except Exception as exc:  # noqa: BLE001 - 拉不到代码也是一种要人看的结论
            logger.warning("workspace not prepared for %s: %s", incident_id, exc)
            return {
                "source": "harness",
                "summary": f"工作区拿不到代码,这一场没开工:{type(exc).__name__}: {exc}",
                "steps": [],
                "counts": {},
                "exhausted": False,
            }

    thread = await _thread_for(payload)

    result = await run_harness(
        command=command,
        workspace=workspace,
        task=build_task(
            incident_id=incident_id,
            signal=signal_from_payload(payload),
            exit_url=exit_url,
            workspace=str(workspace),
            report_path=str(workspace / "report.json"),
            repo=repo,
            branch=branch,
            token=config.settings.harness_token,
            thread=thread,
        ),
        extra_env={
            "GWEI_EXIT_URL": exit_url,
            "GWEI_TOKEN": config.settings.harness_token,
            "GWEI_INCIDENT_ID": incident_id,
            "GWEI_TENANT": payload.get("tenant_slug", ""),
            "GWEI_BINDING": config.settings.default_binding,
        },
        tenant=payload.get("tenant_slug", ""),
        timeout_s=config.settings.harness_timeout_s,
    )
    if result.stderr:
        logger.info("harness %s: %s", incident_id, result.stderr[-400:])
    return result.report


@DBOS.step()
async def run_harness_step(payload: dict) -> dict | None:
    return await _run_harness_impl(payload)


@DBOS.step()
async def handle_incident_step(payload: dict) -> dict | None:
    return await _handle_incident_impl(payload)


async def _open_incident_impl(payload: dict) -> dict:
    from engine.incidents import create_incident_store

    return await create_incident_store().open(
        incident_id=DBOS.workflow_id,
        tenant=payload.get("tenant_slug", ""),
        signal=signal_from_payload(payload),
    )


async def _close_incident_impl(payload: dict, report: dict) -> dict:
    from engine.incidents import create_incident_store

    closed = await create_incident_store().close(DBOS.workflow_id, report=report)
    return closed or {}


@DBOS.step()
async def open_incident_step(payload: dict) -> dict:
    return await _open_incident_impl(payload)


@DBOS.step()
async def close_incident_step(payload: dict, report: dict) -> dict:
    return await _close_incident_impl(payload, report)


def declarative_report(intent: dict, applied: dict) -> dict:
    """声明式路径没有 agent 的报告,就把"提了什么、成了什么"整理成同一份形状。"""
    effects = list(applied.get("applied") or [])
    counts: dict[str, int] = {}
    for item in effects:
        verdict = str(item.get("verdict") or "error")
        counts[verdict] = counts.get(verdict, 0) + 1
    return {
        "source": "declarative",
        "summary": str(intent.get("summary") or ""),
        "steps": [
            {
                "tool": str(item.get("capability") or ""),
                "result": {
                    "verdict": item.get("verdict"),
                    "reason": item.get("reason"),
                },
            }
            for item in effects
        ],
        "counts": counts,
        "exhausted": False,
    }


@DBOS.step()
async def propose_alert_intent_step(payload: dict) -> dict:
    return await _propose_intent_impl(payload, {}, [])


@DBOS.workflow()
async def alert_triage_workflow(payload: dict) -> dict:
    """监控信号:没有补丁、没有回评,只有意图与效果。

    信号本身不携带动作。能做什么由 intent 提供者决定;没有提供者时
    effects 为空,工作流正常结束——不假装做了什么。
    """
    # 开始就写一行:事故开着没收口,说明那一场卡住了——这本身就是信息。
    await open_incident_step(payload)

    harnessed = await run_harness_step(payload)
    if harnessed is not None:
        await close_incident_step(payload, harnessed)
        return harnessed

    handled = await handle_incident_step(payload)
    if handled is not None:
        await close_incident_step(payload, {**handled, "source": handled.get("source") or "agent"})
        return handled

    intent = await propose_alert_intent_step(payload)
    applied = await apply_effects_step(intent, payload)
    await close_incident_step(payload, declarative_report(intent, applied))

    return {
        "signal": (payload.get("signal") or {}).get("subject", ""),
        "intent": intent.get("summary", ""),
        "applied": applied,
    }


@DBOS.workflow()
async def issue_triage_workflow(payload: dict) -> dict:
    """Issue 感知工作流：分析 → 落库 → Hook 观察点 → 起草意图 → 效果落成变更单元。"""
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


def _reply_body(payload: dict, report: dict) -> str:
    """在话题上回一句话。

    有人在这里点了名,平台上做了事,那就要有人看见——只在控制台里留一行不算回话:
    GitHub 上那条评论的人不会打开控制台。
    """
    summary = str(report.get("summary") or "").strip()
    lines = summary.splitlines()
    first = lines[0].strip() if lines else "这一场没有留下结论"

    parts = [f"处理完了:{first}", ""]
    detail = "\n".join(line for line in lines[1:4] if line.strip()).strip()
    if detail:
        parts += [detail, ""]

    counts = report.get("counts") or {}
    if counts:
        parts.append("变更:" + "、".join(f"{name} {value}" for name, value in counts.items()))
    if report.get("exhausted"):
        parts.append("这一场没跑完(超时或额度用尽),需要人接手。")

    parts += [
        "",
        f"事故:{DBOS.workflow_id}",
        "结论、可撤销性与账本在平台的「变更」与「事故」里。",
    ]
    return "\n".join(parts)


async def _already_commented(tenant: str, incident_id: str) -> bool:
    """这一场里 agent 自己回过话了吗。回过就不再补一句——同一个话题上两条机器人。"""
    try:
        rows = await create_ledger().latest(tenant=tenant, limit=50)
    except Exception:  # noqa: BLE001 - 账本读不到就按没回过处理,回话比沉默好
        return False
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("incident_id") or "") != incident_id:
            continue
        effect = row.get("effect")
        if isinstance(effect, dict) and effect.get("capability") == "comment.create":
            return True
    return False


async def _reply_on_topic_impl(payload: dict, report: dict) -> dict:
    repo = payload.get("repo_full_name") or ""
    number = payload.get("issue_number")
    if not repo or number is None:
        return {"posted": False, "reason": "没有可回复的话题"}
    tenant = payload.get("tenant_slug", "")
    if await _already_commented(tenant, DBOS.workflow_id):
        return {"posted": False, "reason": "agent 已经回过话"}

    intent = {
        "version": 1,
        "summary": "回一句这一场的结果",
        "evidence": [{"kind": "issue", "ref": f"{repo}#{number}"}],
        "effects": [
            {
                "capability": "comment.create",
                "args": {
                    "repo": repo,
                    "issue_number": number,
                    "body": _reply_body(payload, report),
                },
            }
        ],
        "rationale": "有人点了名,平台做了事,要在原处说清楚结果;这句回话本身也是一次可撤销的变更。",
    }
    applied = await _apply_effects_impl(
        intent, payload, f"{DBOS.workflow_id}:reply", incident_id=DBOS.workflow_id
    )
    verdicts = [item.get("verdict") for item in applied.get("applied") or []]
    return {"posted": "kept" in verdicts, "verdicts": verdicts}


@DBOS.step()
async def reply_on_topic_step(payload: dict, report: dict) -> dict:
    return await _reply_on_topic_impl(payload, report)


async def _run_agent_impl(payload: dict) -> dict:
    """有人点名要改动:落库 → 开事故 → 交给 harness → 收口 → 回一句话。

    落库是为了这一条需求在控制台里查得到;不跑感知分析——要给 agent 的是原始
    标题与正文,再让另一个模型先把它"分析"一遍只是多一次可能出错的翻译。

    最后一步是回话:不回,那条 @gwei 的人在 GitHub 上什么也看不到,只会以为它没理人。
    """
    await persist_triage_step(payload, {}, "FIX_REQUESTED")
    await open_incident_step(payload)
    report = await run_harness_step(payload) or {}
    await close_incident_step(payload, report)
    await reply_on_topic_step(payload, report)
    return report


@DBOS.workflow()
async def fix_suggestion_workflow(payload: dict) -> dict:
    """@gwei 评论 → 让 agent 去做;没有 agent 就退回补丁建议 + 回评。

    这里不分"修 bug"和"做功能":两者都是"有人要这个仓库变一下"。谁来做这件事由
    部署决定——配了 harness 就让它在工作区里动手,没配就仍然只是给建议。
    """
    if harness_configured():
        return await _run_agent_impl(payload)

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
