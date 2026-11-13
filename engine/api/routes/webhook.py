# engine/api/routes/webhook.py
"""Webhook 入口 —— 各来源的投递归一化后入队。

核心只做四件事:按来源找适配器 → 验签 → 取归一化事件 → 去重入队。
GitHub / GitLab / CNB 的字段名、事件名与签名方式都留在各自适配器里,
工作流只认 `engine/ingest/events.py` 那一种说法。

新增一个来源 = 加一个声明 `webhook.receive` 的适配器插件,这里不加分支。
"""

import hashlib
import logging
import re
import uuid

from dbos import DBOS, SetEnqueueOptions, SetWorkflowID
from fastapi import APIRouter, HTTPException, Request

from engine.ingest import parse_alerts
from engine.ingest.events import header_value
from engine.shared.cache import WEBHOOK_DEDUP_TTL_S, dedup_once
from engine.shared.config import config
from engine.shared.runtime import get_source_adapter
from engine.workflows.pipeline import (
    WORKFLOW_QUEUE,
    alert_triage_workflow,
    fix_suggestion_workflow,
    issue_triage_workflow,
)
from engine.workflows.release import release_workflow

router = APIRouter()
logger = logging.getLogger(__name__)


def _payload_from_event(event: dict) -> dict:
    """归一化事件 → 工作流入参。字段名与来源无关。"""
    repo = event["repo"]
    number = event["number"]
    return {
        "tenant_slug": config.settings.default_tenant_slug,
        "repo_full_name": repo,
        "topic": f"{repo}#{number}",
        "source": event.get("kind", ""),
        # 适配器来源:回评这类效果要按它选提供者,不能都算到 GitHub 头上。
        "source_adapter": event.get("source", ""),
        "is_pull": bool(event.get("is_pull")),
        "repo_github_id": event.get("repo_id"),
        "issue_github_id": event.get("change_id"),
        "issue_number": number,
        "title": event.get("title", ""),
        "body": event.get("body", ""),
        "action": event.get("action", ""),
        "base_ref": event.get("base_ref", ""),
        "head_ref": event.get("head_ref", ""),
        "merge_sha": event.get("merge_sha", ""),
        "url": event.get("url", ""),
    }


def _delivery_id(headers: dict, body: bytes) -> str:
    """投递身份:优先用来源给的,没给就用内容哈希。

    没给唯一 ID 的来源(GitLab/CNB 的某些投递)如果用随机数,重试会被当成
    新投递再跑一场;内容哈希让同一条投递在重试时落在同一个工作流上。
    """
    for name in ("X-GitHub-Delivery", "X-Gitlab-Event-UUID", "X-Request-Id"):
        value = header_value(headers, name)
        if value:
            return value
    return hashlib.sha256(body).hexdigest()[:16]


async def _handle_source_event(
    source: str, request: Request, *, only_kind: str | None = None
) -> dict:
    """一个来源的 Webhook:验签、归一化、去重、入队。"""
    try:
        adapter = get_source_adapter(source)
    except LookupError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if adapter is None:
        raise HTTPException(
            status_code=503,
            detail=f"没有为 {source} 配置 webhook 适配器:装上声明 webhook.receive 的插件再来",
        )

    # 人可能刚在页面上填完密钥:启动时读的是快照,再读一次,不用重启。
    if not adapter.webhook_configured():
        try:
            await adapter.on_startup()
        except Exception:  # noqa: BLE001 - 还是配不全就按"没配"拒收,不在这里炸
            logger.info("webhook adapter %s still unconfigured after reload", source)

    # 没配密钥就是不设防:这个端点会起工作流(容器、模型、PR),不能默认敞开。
    if not adapter.webhook_configured():
        hint = {
            "github": "GITHUB_APP_WEBHOOK_SECRET",
            "gitlab": "GITLAB_WEBHOOK_SECRET",
            "cnb": "CNB_WEBHOOK_TOKEN",
        }.get(source, f"{source.upper()}_WEBHOOK_SECRET")
        raise HTTPException(
            status_code=503,
            detail=f"未配置 {hint},拒绝接收 {source} webhook 投递:这个端点会起工作流,不能默认敞开",
        )

    body = await request.body()
    headers = dict(request.headers)
    if not adapter.verify_webhook(headers, body):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    event = adapter.parse_webhook(headers, body)
    if event is None:
        return {"status": "ignored", "message": "Unsupported or filtered event"}

    if event.get("kind") == "ping":
        return {"status": "ok", "message": "pong"}
    if only_kind is not None and event.get("kind") != only_kind:
        return {"status": "ignored", "message": f"Not a {only_kind} event"}

    payload = _payload_from_event(event)
    delivery = _delivery_id(headers, body)

    # 投递去重(键带租户段):来源会重试投递,防止重复触发工作流
    if not await dedup_once(
        f"gwei:{payload['tenant_slug']}:webhook-dedup:{delivery}",
        WEBHOOK_DEDUP_TTL_S,
    ):
        return {"status": "duplicate", "workflow_id": f"gwei-dedup-{delivery}"}

    kind = event.get("kind")
    if kind == "merge":
        return await _enqueue_workflow("gwei-release", release_workflow, delivery, payload)
    if kind == "comment":
        if "@gwei" not in (payload["body"] or "").lower():
            return {"status": "ignored", "message": "Comment does not mention @gwei"}
        return await _enqueue_workflow("gwei-fix", fix_suggestion_workflow, delivery, payload)
    return await _enqueue_workflow("gwei-triage", issue_triage_workflow, delivery, payload)


async def _enqueue_workflow(prefix: str, workflow, delivery_id: str, payload: dict) -> dict:
    """以投递 ID 为幂等键、租户为分区键入队。

    分区队列的入队必须携带 partition_key（Spike 实测：缺 key 的工作流行会被
    静默创建且永不被执行），因此三个上下文管理器缺一不可：
    SetWorkflowID 幂等 + SetEnqueueOptions 分区 + enqueue_workflow_async。
    """
    workflow_id = f"{prefix}-{delivery_id}"
    with SetWorkflowID(workflow_id), SetEnqueueOptions(
        queue_partition_key=payload["tenant_slug"]
    ):
        await DBOS.enqueue_workflow_async(WORKFLOW_QUEUE, workflow, payload)
    subject = (
        f"{payload['repo_full_name']}#{payload['issue_number']}"
        if payload.get("repo_full_name")
        else (payload.get("signal") or {}).get("subject", "-")
    )
    logger.info(
        "Enqueued workflow %s (tenant=%s %s)", workflow_id, payload["tenant_slug"], subject
    )
    return {"status": "queued", "workflow_id": workflow_id}


@router.post("/webhook/github")
async def github_webhook(request: Request):
    """GitHub Webhook(issues / issue_comment / pull_request / ping)。"""
    return await _handle_source_event("github", request)


@router.post("/webhook/github/comment")
async def github_comment_webhook(request: Request):
    """GitHub 评论专用入口:只接 issue_comment。"""
    return await _handle_source_event("github", request, only_kind="comment")


@router.post("/webhook/gitlab")
async def gitlab_webhook(request: Request):
    """GitLab Webhook(当前接合并请求的合并事件)。"""
    return await _handle_source_event("gitlab", request)


@router.post("/webhook/cnb")
async def cnb_webhook(request: Request):
    """CNB Webhook(当前接 PullRequestEvent 的合并事件)。"""
    return await _handle_source_event("cnb", request)


@router.post("/webhook/alertmanager")
async def alertmanager_webhook(request: Request):
    """监控信号入口。

    Alertmanager 不会签名,只认共享令牌。没配令牌就直接拒绝——这个端点会起工作流,
    不应该默认敞开。
    """
    token = config.settings.alertmanager_webhook_token
    if not token:
        raise HTTPException(
            status_code=503, detail="未配置 ALERTMANAGER_WEBHOOK_TOKEN,拒绝接收监控信号"
        )
    if request.headers.get("X-Gwei-Token", "") != token:
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    signals = parse_alerts(payload)
    if not signals:
        return {"status": "ignored", "message": "没有 firing 的告警"}

    tenant = config.settings.default_tenant_slug
    queued: list[dict] = []
    for signal in signals:
        # 同一条告警会被重复投递;fingerprint + 起始时间是它这一次发作的身份
        occurrence = "".join(ch for ch in signal.get("started_at", "") if ch.isalnum())
        delivery = _safe_id(signal["ref"] or signal["title"], occurrence)
        if not await dedup_once(f"gwei:{tenant}:alert-dedup:{delivery}", WEBHOOK_DEDUP_TTL_S):
            continue
        queued.append(
            await _enqueue_workflow(
                "gwei-alert",
                alert_triage_workflow,
                delivery,
                {"tenant_slug": tenant, "signal": signal},
            )
        )

    if not queued:
        return {"status": "duplicate", "message": "告警已经处理过"}
    return {"status": "queued", "count": len(queued), "workflows": queued}


def _safe_id(*parts: str) -> str:
    """工作流 id 只留安全字符:告警标题可能带空格和中文。"""
    raw = "-".join(part for part in parts if part)
    return re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-") or "alert"
