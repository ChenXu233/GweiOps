# plugins/builtin/adapters/cnb/plugin.py
"""CNB(cnb.cool)适配器 —— 目前负责"合并"这一件事。

CNB 的合并事件是 `PullRequestEvent` + action=closed + merged_at 非空。和 GitLab
一样,字段名留在这一层,核心只收到一次 `kind="merge"`。
"""

from __future__ import annotations

import hmac
import json
from typing import Any, Dict

from engine.ingest.events import EventError, event as normalized_event, header_value
from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType

from .config import CNBConfig

SOURCE = "cnb"


class CNBAdapter(PluginBase):
    def __init__(self) -> None:
        self.config: CNBConfig | None = None
        self.binding = "cnb"
        self.tenant = ""
        self.source = SOURCE
        # 没配密钥时,入口按这个名字告诉人该去填什么(核心不维护来源清单)。
        self.config_hint = "CNB_WEBHOOK_TOKEN"

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="cnb-adapter",
            version="0.1.0",
            type=PluginType.ADAPTER,
            description="CNB(cnb.cool)适配器:接收 PullRequestEvent,把合并翻译成平台事件",
            capabilities=["webhook.receive", "webhook.verify"],
            config={
                "required": ["CNB_WEBHOOK_TOKEN"],
                "optional": ["CNB_BASE_URL", "CNB_TOKEN", "CNB_WEBHOOK_HEADER"],
            },
        )

    async def on_startup(self) -> None:
        self.config = CNBConfig()

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
        return bool(self.config and self.config.webhook_token)

    def verify_webhook(self, headers: Dict[str, Any], body: bytes) -> bool:
        if not self.webhook_configured():
            return False
        sent = header_value(headers, self.config.webhook_header)
        return bool(sent) and hmac.compare_digest(sent, self.config.webhook_token)

    def parse_webhook(self, headers: Dict[str, Any], body: bytes) -> Dict[str, Any] | None:
        try:
            payload = json.loads(body)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return normalize_pull_request_event(payload)
        except EventError:
            return None


def normalize_pull_request_event(payload: dict[str, Any]) -> dict[str, Any] | None:
    """CNB PullRequestEvent → 归一化事件;不是合并就返回 None。"""
    if payload.get("type") != "PullRequestEvent":
        return None
    if payload.get("action") != "closed":
        return None

    pull = payload.get("pull_request") or {}
    merged = (
        bool(pull.get("merged"))
        or str(pull.get("state") or "") == "merged"
        or bool(pull.get("merged_at"))
    )
    if not merged:
        return None

    repo_raw = payload.get("repo") or {}
    repo = repo_raw.get("path") or ""
    if not repo:
        return None
    repo_id = repo_raw.get("id")

    base = pull.get("base") or {}
    head = pull.get("head") or {}
    # CNB 的 PullRequestEvent 不总是带 merge_commit_sha;没有就交给发布侧
    # 如实报告"缺少合并提交",不拿 head 的分支名冒充。
    merge_sha = str(pull.get("merge_commit_sha") or payload.get("merge_commit_sha") or "")
    return normalized_event(
        kind="merge",
        source=SOURCE,
        repo=repo,
        repo_id=repo_id,
        change_id=pull.get("id") or payload.get("id"),
        number=pull.get("number") or payload.get("number"),
        title=pull.get("title") or "",
        body=pull.get("body") or "",
        action="merged",
        base_ref=base.get("ref") or "",
        head_ref=head.get("ref") or "",
        merge_sha=merge_sha,
        url=pull.get("html_url") or "",
        sender=((payload.get("actor") or {}).get("username") or ""),
    )
