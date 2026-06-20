# engine/api/routes/webhook.py
"""Webhook 路由 - 处理 GitHub Webhook 事件。"""

import logging

from fastapi import APIRouter, Request, HTTPException

router = APIRouter()
logger = logging.getLogger(__name__)

# 延迟导入的插件实例缓存
_adapter_instance = None
_sensor_instance = None


def get_adapter():
    """获取 GitHubAppAdapter 实例（延迟导入避免循环依赖）。"""
    global _adapter_instance
    if _adapter_instance is None:
        import importlib
        module = importlib.import_module("plugins.builtin.adapters.github-app.plugin")
        _adapter_instance = module.GitHubAppAdapter()
    return _adapter_instance


def get_sensor():
    """获取 SensorAgent 实例（延迟导入避免循环依赖）。"""
    global _sensor_instance
    if _sensor_instance is None:
        from plugins.builtin.agents.sensor.plugin import SensorAgent
        _sensor_instance = SensorAgent()
    return _sensor_instance


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


async def _process_issue_event(adapter, sensor, headers: dict, body: bytes) -> dict:
    """处理 Issue 事件（issues opened/edited）。"""
    # 通过 adapter 解析事件
    event = adapter.webhook_handler.parse_event(headers, body)
    if event is None:
        return {"status": "ignored", "message": "Unsupported or filtered event"}

    # 提取 issue 信息
    issue_info = adapter.webhook_handler.extract_issue_info(event)
    if issue_info is None:
        return {"status": "ignored", "message": "Could not extract issue info"}

    logger.info(
        f"Issue event: {event['type']}/{event['action']} "
        f"repo={issue_info['owner']}/{issue_info['repo']} "
        f"issue=#{issue_info['issue_number']}"
    )

    # 通过 sensor 分析 issue
    sensor_data = {
        "issue": {
            "title": issue_info["title"],
            "body": issue_info["body"],
        }
    }
    analysis = await sensor.handle_event("issue.created", sensor_data)

    # 如果分析成功，通过 adapter 回复评论
    if analysis.get("reply") and issue_info.get("repo") and issue_info.get("issue_number"):
        repo = f"{issue_info['owner']}/{issue_info['repo']}"
        try:
            await adapter.execute_task("create_comment", {
                "repo": repo,
                "issue_number": issue_info["issue_number"],
                "body": analysis["reply"],
            })
            logger.info(f"Posted analysis comment on {repo}#{issue_info['issue_number']}")
        except Exception as e:
            logger.error(f"Failed to post comment: {e}")

    return {
        "status": "ok",
        "event_type": event["type"],
        "action": event["action"],
        "issue_info": issue_info,
        "analysis": analysis,
    }


async def _process_comment_event(adapter, sensor, headers: dict, body: bytes) -> dict:
    """处理评论事件（issue_comment created/edited），仅当评论包含 @gwei 时触发。"""
    event = adapter.webhook_handler.parse_event(headers, body)
    if event is None:
        return {"status": "ignored", "message": "Unsupported or filtered event"}

    issue_info = adapter.webhook_handler.extract_issue_info(event)
    if issue_info is None:
        return {"status": "ignored", "message": "Could not extract comment info"}

    comment_body = issue_info.get("comment_body", "")

    # 检查是否包含 @gwei 触发词
    if "@gwei" not in comment_body.lower():
        return {"status": "ignored", "message": "Comment does not mention @gwei"}

    logger.info(
        f"Comment event with @gwei: repo={issue_info['owner']}/{issue_info['repo']} "
        f"issue=#{issue_info['issue_number']} comment_id={issue_info.get('comment_id')}"
    )

    # 通过 sensor 分析评论内容
    sensor_data = {
        "issue": {
            "title": f"Comment on issue #{issue_info['issue_number']}",
            "body": comment_body,
        }
    }
    analysis = await sensor.handle_event("issue_comment.created", sensor_data)

    # 回复分析结果
    if analysis.get("reply") and issue_info.get("repo") and issue_info.get("issue_number"):
        repo = f"{issue_info['owner']}/{issue_info['repo']}"
        try:
            await adapter.execute_task("create_comment", {
                "repo": repo,
                "issue_number": issue_info["issue_number"],
                "body": analysis["reply"],
            })
            logger.info(f"Posted reply to @gwei mention on {repo}#{issue_info['issue_number']}")
        except Exception as e:
            logger.error(f"Failed to post reply: {e}")

    return {
        "status": "ok",
        "event_type": event["type"],
        "action": event["action"],
        "issue_info": issue_info,
        "analysis": analysis,
    }


@router.post("/webhook/github")
async def github_webhook(request: Request):
    """处理 GitHub Webhook Issue 事件。"""
    body = await _validate_webhook(request)
    headers = _build_headers_dict(request)
    event_type = headers.get("X-GitHub-Event", "")

    logger.info(f"Received webhook: {event_type}, delivery: {headers.get('X-GitHub-Delivery')}")

    adapter = get_adapter()
    sensor = get_sensor()

    if event_type == "issues":
        return await _process_issue_event(adapter, sensor, headers, body)

    elif event_type == "issue_comment":
        return await _process_comment_event(adapter, sensor, headers, body)

    elif event_type == "ping":
        return {"status": "ok", "message": "pong"}

    return {"status": "ignored", "event": event_type}


@router.post("/webhook/github/comment")
async def github_comment_webhook(request: Request):
    """处理 GitHub Webhook 评论事件（@gwei 触发）。"""
    body = await _validate_webhook(request)
    headers = _build_headers_dict(request)
    event_type = headers.get("X-GitHub-Event", "")

    logger.info(f"Received comment webhook: {event_type}, delivery: {headers.get('X-GitHub-Delivery')}")

    if event_type != "issue_comment":
        return {"status": "ignored", "message": "Not a comment event"}

    adapter = get_adapter()
    sensor = get_sensor()
    return await _process_comment_event(adapter, sensor, headers, body)
