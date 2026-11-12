# engine/api/routes/webhook.py
"""Webhook 路由 - 处理 GitHub Webhook 事件。

职责收窄为：验签 → 解析 → 去重 → 入 DBOS 队列。
实际处理逻辑在 engine/workflows/pipeline.py 的工作流中持久化执行。
"""

import json
import logging
import re
import uuid

from dbos import DBOS, SetEnqueueOptions, SetWorkflowID
from fastapi import APIRouter, HTTPException, Request

from engine.ingest import parse_alerts
from engine.shared.cache import WEBHOOK_DEDUP_TTL_S, dedup_once
from engine.shared.config import config
from engine.shared.runtime import get_adapter, get_sensor  # noqa: F401 — 兼容既有导入
from engine.workflows.pipeline import (
    WORKFLOW_QUEUE,
    alert_triage_workflow,
    fix_suggestion_workflow,
    issue_triage_workflow,
)

router = APIRouter()
logger = logging.getLogger(__name__)


async def _validate_webhook(request: Request) -> bytes:
    """验证 Webhook 请求并返回 body。"""
    adapter = get_adapter()

    # 确保 adapter 已初始化
    if adapter.config is None:
        await adapter.on_startup()

    body = await request.body()
    headers = dict(request.headers)

    # 人可能刚在页面上填完密钥:配置是启动时读的一份快照,再读一次,
    # 不用为了一个密钥重启服务。读回来还是空的,才按"没配"处理。
    if not adapter.config.webhook_secret:
        try:
            await adapter.on_startup()
        except Exception:  # noqa: BLE001 - 还是配不全就走下面的拒收,不在这里炸
            logger.info("webhook secret still unset after reloading plugin config")

    # 没配密钥就是不设防,而这个端点会起工作流(容器、模型、PR)。放在公网上
    # 等于谁都能花你的钱、用你的 App 身份说话 —— 宁可拒收,等配置补齐。
    if not adapter.config.webhook_secret:
        raise HTTPException(
            status_code=503,
            detail=(
                "未配置 GITHUB_APP_WEBHOOK_SECRET,拒绝接收 GitHub 投递:"
                "这个端点会起工作流,不能默认敞开"
            ),
        )

    signature = headers.get("x-hub-signature-256", "")
    if not adapter.webhook_handler.verify_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    return body


def _build_headers_dict(request: Request) -> dict:
    """从 Request 构建 headers 字典（键名与 GitHub 一致）。"""
    return {
        "X-GitHub-Event": request.headers.get("X-GitHub-Event", ""),
        "X-GitHub-Delivery": request.headers.get("X-GitHub-Delivery", ""),
        "X-Hub-Signature-256": request.headers.get("X-Hub-Signature-256", ""),
    }


def _extract_payload(raw: dict, issue_info: dict, event_type: str) -> dict | None:
    """从原始 payload 提取工作流入参（GitHub 数字 ID 用于业务表幂等 upsert）。"""
    repo = raw.get("repository") or {}
    issue = raw.get("issue") or {}
    comment = raw.get("comment") or {}
    repo_id = repo.get("id")
    issue_id = issue.get("id")
    if repo_id is None or issue_id is None:
        logger.warning("Webhook payload missing repository.id/issue.id; ignoring")
        return None

    if event_type == "issue_comment":
        # 评论触发：以评论内容为分析对象，标题取真实 Issue 标题
        body = comment.get("body") or ""
        source = "comment"
    else:
        body = issue.get("body") or ""
        source = "issue"

    return {
        "tenant_slug": config.settings.default_tenant_slug,
        "repo_full_name": f"{issue_info['owner']}/{issue_info['repo']}",
        "repo_github_id": repo_id,
        "issue_github_id": issue_id,
        "issue_number": issue_info["issue_number"],
        "title": issue.get("title") or issue_info["title"],
        "body": body,
        "source": source,
    }


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


async def _handle_event(event_type: str, delivery_id: str, headers: dict, body: bytes) -> dict:
    adapter = get_adapter()

    event = adapter.webhook_handler.parse_event(headers, body)
    if event is None:
        return {"status": "ignored", "message": "Unsupported or filtered event"}

    action = event.get("action", "")
    if event_type == "issues" and action not in ("opened", "edited"):
        return {"status": "ignored", "message": f"Unsupported action: {action}"}
    if event_type == "issue_comment" and action not in ("created", "edited"):
        return {"status": "ignored", "message": f"Unsupported action: {action}"}

    issue_info = adapter.webhook_handler.extract_issue_info(event)
    if issue_info is None:
        return {"status": "ignored", "message": "Could not extract issue info"}

    payload = _extract_payload(json.loads(body), issue_info, event_type)
    if payload is None:
        return {"status": "ignored", "message": "Missing repository/issue id"}

    # 投递去重（键带租户段）：GitHub 会重试投递，防止重复触发工作流
    if not await dedup_once(
        f"gwei:{payload['tenant_slug']}:webhook-dedup:{delivery_id}",
        WEBHOOK_DEDUP_TTL_S,
    ):
        return {"status": "duplicate", "workflow_id": f"gwei-dedup-{delivery_id}"}

    if event_type == "issue_comment":
        if "@gwei" not in (payload["body"] or "").lower():
            return {"status": "ignored", "message": "Comment does not mention @gwei"}
        return await _enqueue_workflow("gwei-fix", fix_suggestion_workflow, delivery_id, payload)

    return await _enqueue_workflow("gwei-triage", issue_triage_workflow, delivery_id, payload)


@router.post("/webhook/github")
async def github_webhook(request: Request):
    """处理 GitHub Webhook（issues / issue_comment / ping）。"""
    body = await _validate_webhook(request)
    headers = _build_headers_dict(request)
    event_type = headers.get("X-GitHub-Event", "")
    delivery_id = headers.get("X-GitHub-Delivery", "") or str(uuid.uuid4())

    logger.info(f"Received webhook: {event_type}, delivery: {headers.get('X-GitHub-Delivery')}")

    if event_type == "ping":
        return {"status": "ok", "message": "pong"}

    if event_type in ("issues", "issue_comment"):
        return await _handle_event(event_type, delivery_id, headers, body)

    return {"status": "ignored", "event": event_type}


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


@router.post("/webhook/github/comment")
async def github_comment_webhook(request: Request):
    """处理 GitHub Webhook 评论事件（@gwei 触发）。"""
    body = await _validate_webhook(request)
    headers = _build_headers_dict(request)
    event_type = headers.get("X-GitHub-Event", "")
    delivery_id = headers.get("X-GitHub-Delivery", "") or str(uuid.uuid4())

    logger.info(f"Received comment webhook: {event_type}, delivery: {headers.get('X-GitHub-Delivery')}")

    if event_type != "issue_comment":
        return {"status": "ignored", "message": "Not a comment event"}

    return await _handle_event(event_type, delivery_id, headers, body)
