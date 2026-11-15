# engine/api/routes/webhook.py
"""Webhook 入口 —— 各来源的投递归一化后入队。

核心只做四件事:按来源找适配器 → 验签 → 取归一化事件 → 去重入队。
GitHub / GitLab / CNB 的字段名、事件名与签名方式都留在各自适配器里,
工作流只认 `engine/ingest/events.py` 那一种说法。

新增一个来源 = 加一个声明 `webhook.receive` 的适配器插件,这里不加分支。
"这条评论算不算叫我"也归适配器声明(`mentions`),核心不认识 `@gwei` 这个名字。
"""

import hashlib
import logging
import re
import uuid

from fastapi import APIRouter, HTTPException, Request

from engine.ingest.events import header_value
from engine.ingest.source import mentions_prompt, source_adapter
from engine.shared.cache import WEBHOOK_DEDUP_TTL_S, dedup_once
from engine.shared.config import config
from engine.workflows.pipeline import (
    WORKFLOW_QUEUE,
    alert_triage_workflow,
    fix_suggestion_workflow,
    issue_triage_workflow,
)
from engine.workflows.queue import enqueue_workflow
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


async def _handle_source_event(source: str, request: Request) -> dict:
    """一个来源的 Webhook:验签、归一化、去重、入队。"""
    try:
        adapter = source_adapter(source)
    except LookupError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # 人可能刚在页面上填完密钥:启动时读的是快照,再读一次,不用重启。
    if not adapter.webhook_configured():
        try:
            await adapter.on_startup()
        except Exception:  # noqa: BLE001 - 还是配不全就按"没配"拒收,不在这里炸
            logger.info("webhook adapter %s still unconfigured after reload", source)

    # 没配密钥就是不设防:这个端点会起工作流(容器、模型、PR),不能默认敞开。
    if not adapter.webhook_configured():
        hint = getattr(adapter, "config_hint", "") or f"{source.upper()}_WEBHOOK_SECRET"
        raise HTTPException(
            status_code=503,
            detail=f"未配置 {hint},拒绝接收 {source} webhook 投递:这个端点会起工作流,不能默认敞开",
        )

    body = await request.body()
    headers = dict(request.headers)
    if not adapter.verify_webhook(headers, body):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # 适配器可以产出信号,而不是"issue/comment/merge"那种事件:告警类来源走这条路,
    # 和 GitHub 类来源共用同一个入口、同一套验签与去重。
    if getattr(adapter, "produces", "event") == "signal":
        return await _enqueue_signals(source, adapter, headers, body)

    event = adapter.parse_webhook(headers, body)
    if event is None:
        return {"status": "ignored", "message": "Unsupported or filtered event"}

    if event.get("kind") == "ping":
        return {"status": "ok", "message": "pong"}

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
        # 触发词是这个来源自己的事:CNB 上人叫 `@CodeBuddy`,GitHub 上叫 `@gwei`。
        if not mentions_prompt(adapter, payload["body"]):
            return {"status": "ignored", "message": f"{source} 上的评论没叫平台"}
        return await _enqueue_workflow("gwei-fix", fix_suggestion_workflow, delivery, payload)
    return await _enqueue_workflow("gwei-triage", issue_triage_workflow, delivery, payload)


async def _enqueue_workflow(prefix: str, workflow, delivery_id: str, payload: dict) -> dict:
    """入队,并为这次投递留一行日志。入队的规矩本身在 engine/workflows/queue.py。"""
    queued = await enqueue_workflow(prefix, workflow, delivery_id, payload)
    workflow_id = queued["workflow_id"]
    subject = (
        f"{payload['repo_full_name']}#{payload['issue_number']}"
        if payload.get("repo_full_name")
        else (payload.get("signal") or {}).get("subject", "-")
    )
    logger.info(
        "Enqueued workflow %s (tenant=%s %s)", workflow_id, payload["tenant_slug"], subject
    )
    return queued


async def _enqueue_signals(source: str, adapter, headers: dict, body: bytes) -> dict:
    """一次投递里的若干条信号:各自去重、各自入队,一条重复不拖累其余。"""
    try:
        signals = adapter.parse_signals(headers, body)
    except Exception as exc:  # noqa: BLE001 - 解析失败是 400,不是 500
        raise HTTPException(
            status_code=400, detail=f"{source} 投递解析失败: {exc}"
        ) from exc

    tenant = config.settings.default_tenant_slug
    queued: list[dict] = []
    for signal in signals or []:
        if not isinstance(signal, dict) or not signal.get("title"):
            continue
        # 同一个 fingerprint 再次 firing 是另一次发作,所以去重键带上 occurrence。
        delivery = _safe_id(
            str(signal.get("ref") or signal.get("subject") or ""),
            str(signal.get("occurrence") or ""),
        )
        if not await dedup_once(f"gwei:{tenant}:signal-dedup:{delivery}", WEBHOOK_DEDUP_TTL_S):
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
        return {
            "status": "duplicate" if signals else "ignored",
            "message": "这次投递里的信号都处理过了" if signals else "没有需要处理的信号",
        }
    return {"status": "queued", "count": len(queued), "workflows": queued}


@router.post("/webhook/{source}")
async def source_webhook(source: str, request: Request):
    """任何来源的投递。

    核心这里不认识 GitHub、GitLab、CNB、Alertmanager、Caddy、云雀中的任何一个:
    它按 `source` 找声明了 `webhook.receive` 的适配器,由适配器验签并翻译。
    接一个新的来源 = 装一个适配器插件,这里不加分支、不加一家专用的入口。
    """
    return await _handle_source_event(source, request)


def _safe_id(*parts: str) -> str:
    """工作流 id 只留安全字符:告警标题可能带空格和中文。"""
    raw = "-".join(part for part in parts if part)
    return re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-") or "alert"
