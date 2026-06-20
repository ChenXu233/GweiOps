# plugins/builtin/adapters/github-app/handlers.py
import hashlib
import hmac
import json
from typing import Dict, Any, Optional
from .config import GitHubAppConfig


class WebhookHandler:
    """GitHub Webhook 处理器。"""

    def __init__(self, config: GitHubAppConfig):
        self.config = config

    def verify_signature(self, body: bytes, signature_header: str) -> bool:
        """验证 Webhook 签名。"""
        if not signature_header:
            return False

        if not self.config.webhook_secret:
            return True  # 未配置 secret 时跳过验证

        try:
            mac = hmac.new(
                self.config.webhook_secret.encode(),
                body,
                hashlib.sha256,
            )
            expected = f"sha256={mac.hexdigest()}"
            return hmac.compare_digest(expected, signature_header)
        except Exception:
            return False

    def parse_event(self, headers: Dict[str, str], body: bytes) -> Optional[Dict[str, Any]]:
        """解析 Webhook 事件。"""
        event_type = headers.get("X-GitHub-Event", "")

        if event_type == "ping":
            return {"type": "ping"}

        if event_type not in ("issues", "issue_comment"):
            return None

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return None

        action = payload.get("action", "")

        # 只处理创建和编辑事件
        if event_type == "issues" and action not in ("opened", "edited"):
            return None

        if event_type == "issue_comment" and action not in ("created", "edited"):
            return None

        return {
            "type": event_type,
            "action": action,
            "payload": payload,
        }

    def extract_issue_info(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """提取 Issue 信息。"""
        payload = event.get("payload", {})

        if event["type"] == "issues":
            issue = payload.get("issue", {})
            repo = payload.get("repository", {})
            return {
                "owner": repo.get("owner", {}).get("login", ""),
                "repo": repo.get("name", ""),
                "issue_number": issue.get("number"),
                "title": issue.get("title", ""),
                "body": issue.get("body", ""),
                "action": event["action"],
                "sender": payload.get("sender", {}).get("login", ""),
            }

        if event["type"] == "issue_comment":
            issue = payload.get("issue", {})
            comment = payload.get("comment", {})
            repo = payload.get("repository", {})
            return {
                "owner": repo.get("owner", {}).get("login", ""),
                "repo": repo.get("name", ""),
                "issue_number": issue.get("number"),
                "comment_id": comment.get("id"),
                "comment_body": comment.get("body", ""),
                "action": event["action"],
                "sender": payload.get("sender", {}).get("login", ""),
            }

        return None
