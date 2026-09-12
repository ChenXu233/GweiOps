# engine/api/routes/webhook.py
"""Webhook 路由 - 处理 GitHub Webhook 事件。

职责收窄为：验签 → 解析 → 去重 → 入 DBOS 队列。
实际处理逻辑在 engine/workflows/pipeline.py 的工作流中持久化执行。
"""

import json
import logging
import uuid

from dbos import DBOS, SetWorkflowID
from fastapi import APIRouter, HTTPException, Request

from engine.shared.cache import WEBHOOK_DEDUP_TTL_S, dedup_once
from engine.shared.runtime import get_adapter, get_sensor  # noqa: F401 — 兼容既有导入
from engine.workflows.pipeline import (
    WORKFLOW_QUEUE,
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

    # 验证签名
    signature = headers.get("x-hub-signature-256", "")
    if adapter.config.webhook_secret:
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
        "repo_full_name": f"{issue_info['owner']}/{issue_info['repo']}",
        "repo_github_id": repo_id,
        "issue_github_id": issue_id,
        "issue_number": issue_info["issue_number"],
        "title": issue.get("title") or issue_info["title"],
        "body": body,
        "source": source,
    }


async def _enqueue_workflow(prefix: str, workflow, delivery_id: str, payload: dict) -> dict:
    """以投递 ID 为幂等键入队（Redis 去重失效时由 DBOS workflow ID 兜底）。"""
    workflow_id = f"{prefix}-{delivery_id}"
    with SetWorkflowID(workflow_id):
        await DBOS.enqueue_workflow_async(WORKFLOW_QUEUE, workflow, payload)
    logger.info(
        "Enqueued workflow %s (%s#%s)",
        workflow_id,
        payload["repo_full_name"],
        payload["issue_number"],
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

    # 投递去重：GitHub 会重试投递，防止重复触发工作流
    if not await dedup_once(f"gwei:webhook-dedup:{delivery_id}", WEBHOOK_DEDUP_TTL_S):
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
