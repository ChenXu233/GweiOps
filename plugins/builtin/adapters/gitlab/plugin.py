# plugins/builtin/adapters/gitlab/plugin.py
"""GitLab 适配器 —— 目前负责"合并"这一件事。

GitLab 的合并事件叫 merge_request、字段是 object_attributes.*;核心不认识这些。
适配器验签、解析、归一化,核心只收到一次 `kind="merge"` 事件。

只做合并触发是刻意的:回评、开 MR 需要项目访问令牌与另一套 API,等那条链路
真要用时再在这里补能力,而不是先声明一个调不通的效果。
"""

from __future__ import annotations

import hmac
import json
from typing import Any, Dict

from engine.ingest.events import EventError, event as normalized_event, header_value
from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType

from .config import GitLabConfig

SOURCE = "gitlab"


class GitLabAdapter(PluginBase):
    def __init__(self) -> None:
        self.config: GitLabConfig | None = None
        self.binding = "gitlab"  # 这个适配器服务的目标;效果按它解析
        self.tenant = ""
        self.source = SOURCE

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="gitlab-adapter",
            version="0.1.0",
            type=PluginType.ADAPTER,
            description="GitLab 适配器:接收合并请求 Webhook,把合并翻译成平台事件",
            capabilities=["webhook.receive", "webhook.verify"],
            config={
                "required": ["GITLAB_WEBHOOK_SECRET"],
                "optional": ["GITLAB_BASE_URL", "GITLAB_TOKEN"],
            },
        )

    async def on_startup(self) -> None:
        self.config = GitLabConfig()

    async def on_shutdown(self) -> None:
        self.config = None

    async def health_check(self) -> bool:
        return self.config is not None

    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "ignored", "event": event}

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "error", "message": f"Unknown task: {task}"}

    # -- Webhook:验签与归一化 --------------------------------------

    def webhook_configured(self) -> bool:
        return bool(self.config and self.config.webhook_secret)

    def verify_webhook(self, headers: Dict[str, Any], body: bytes) -> bool:
        if not self.webhook_configured():
            return False
        sent = header_value(headers, "X-Gitlab-Token")
        return bool(sent) and hmac.compare_digest(sent, self.config.webhook_secret)

    def parse_webhook(self, headers: Dict[str, Any], body: bytes) -> Dict[str, Any] | None:
        """解析 GitLab 投递;不是"合并"就返回 None(这个适配器只接合并)。"""
        try:
            payload = json.loads(body)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return normalize_merge_request(payload)
        except EventError:
            return None


def normalize_merge_request(payload: dict[str, Any]) -> dict[str, Any] | None:
    """GitLab Merge Request Hook → 归一化事件。

    合并事件有两种说法:action=merge,或 state=merged。两者任一成立都算,
    因为 GitLab 不同版本的投递字段不完全一致。
    """
    if payload.get("object_kind") != "merge_request":
        return None

    attrs = payload.get("object_attributes") or {}
    if attrs.get("action") not in ("merge", "merged") and attrs.get("state") != "merged":
        return None

    project = payload.get("project") or {}
    repo = project.get("path_with_namespace") or ""
    if not repo:
        return None

    # 合并提交是发布的输入;GitLab 在合并后给 merge_commit_sha。
    merge_sha = str(attrs.get("merge_commit_sha") or payload.get("merge_commit_sha") or "")
    return normalized_event(
        kind="merge",
        source=SOURCE,
        repo=repo,
        repo_id=project.get("id"),
        change_id=attrs.get("id"),
        number=attrs.get("iid"),
        title=attrs.get("title") or "",
        body=attrs.get("description") or "",
        action="merged",
        base_ref=attrs.get("target_branch") or "",
        head_ref=attrs.get("source_branch") or "",
        merge_sha=merge_sha,
        url=attrs.get("url") or "",
        sender=((payload.get("user") or {}).get("username") or ""),
    )
