# plugins/builtin/adapters/github-app/handlers.py
import hashlib
import hmac
import json
from typing import Dict, Any, Optional

from engine.ingest.events import event as normalized_event, header_value

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
        event_type = header_value(headers, "X-GitHub-Event")

        if event_type == "ping":
            return {"type": "ping"}

        if event_type not in ("issues", "issue_comment", "pull_request"):
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

        # 合并是一次 pull_request closed;关掉不合并的 PR 不算审核通过。
        if event_type == "pull_request" and action != "closed":
            return None

        return {
            "type": event_type,
            "action": action,
            "payload": payload,
        }

    def normalize_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """GitHub 语法 → 平台归一化事件。核心不再认识 pull_request 这些字段。"""
        event_type = event.get("type", "")
        payload = event.get("payload") or {}

        if event_type == "ping":
            return normalized_event(kind="ping", source="github")

        repo_raw = payload.get("repository") or {}
        owner = (repo_raw.get("owner") or {}).get("login", "")
        repo = f"{owner}/{repo_raw.get('name', '')}" if owner or repo_raw.get("name") else ""
        repo_id = repo_raw.get("id")
        sender = (payload.get("sender") or {}).get("login", "")
        action = event.get("action", "")

        if event_type == "issues":
            issue = payload.get("issue") or {}
            return normalized_event(
                kind="issue",
                source="github",
                repo=repo,
                repo_id=repo_id,
                change_id=issue.get("id"),
                number=issue.get("number"),
                title=issue.get("title") or "",
                body=issue.get("body") or "",
                action=action,
                sender=sender,
            )

        if event_type == "issue_comment":
            issue = payload.get("issue") or {}
            comment = payload.get("comment") or {}
            return normalized_event(
                kind="comment",
                source="github",
                repo=repo,
                repo_id=repo_id,
                change_id=issue.get("id"),
                number=issue.get("number"),
                title=issue.get("title") or "",
                body=comment.get("body") or "",
                action=action,
                is_pull=bool(issue.get("pull_request")),
                sender=sender,
            )

        if event_type == "pull_request":
            pull = payload.get("pull_request") or {}
            # 关掉不合并的 PR 不是审核通过:不产生事件。
            if not pull.get("merged"):
                return None
            base = pull.get("base") or {}
            head = pull.get("head") or {}
            return normalized_event(
                kind="merge",
                source="github",
                repo=repo,
                repo_id=repo_id,
                change_id=pull.get("id"),
                number=pull.get("number"),
                title=pull.get("title") or "",
                body=pull.get("body") or "",
                action="merged",
                base_ref=base.get("ref", ""),
                head_ref=head.get("ref", ""),
                merge_sha=pull.get("merge_commit_sha") or "",
                url=pull.get("html_url", ""),
                sender=sender,
            )

        return None
