# plugins/builtin/adapters/github-app/plugin.py
"""GitHub App Adapter 插件 - 通过 GitHub App 进行交互。"""

import json
from pathlib import Path
from typing import Any, Dict

import yaml

from engine.change_unit import Effect, Window
from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType
from .config import GitHubAppConfig
from .client import GitHubAppClient
from .handlers import WebhookHandler


class GitHubAppAdapter(PluginBase):
    """GitHub App 适配器插件，使用 GitHub App 认证进行 API 调用和 Webhook 处理。"""

    def __init__(self):
        self.config: GitHubAppConfig = None
        self.client: GitHubAppClient = None
        self.webhook_handler: WebhookHandler = None
        # 变更单元:这个适配器服务的目标与租户。GitHub 侧的目标是"这个适配器所连的 GitHub"。
        self.binding = "github"
        self.tenant = ""

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="github-app-adapter",
            version="1.0.0",
            type=PluginType.ADAPTER,
            description="GitHub App 适配器，通过 GitHub App 进行认证和交互",
            triggers=[
                {
                    "type": "event",
                    "events": ["webhook.received"],
                }
            ],
            capabilities=[
                "issue.read", "issue.write",
                "comment.read", "comment.write",
                "label.write",
                "webhook.receive", "webhook.verify",
            ],
            config={
                "required": ["GITHUB_APP_APP_ID", "GITHUB_APP_PRIVATE_KEY"],
                "optional": ["GITHUB_APP_WEBHOOK_SECRET", "GITHUB_APP_INSTALLATION_ID"],
            },
        )

    async def on_startup(self):
        """启动时初始化并验证配置。"""
        self.config = GitHubAppConfig()

        # 验证配置
        errors = self.config.validate()
        if errors:
            raise ValueError(f"GitHub App 配置错误: {'; '.join(errors)}")

        self.client = GitHubAppClient(self.config)
        self.webhook_handler = WebhookHandler(self.config)

    async def on_shutdown(self):
        """关闭时释放资源。"""
        self.client = None
        self.webhook_handler = None
        self.config = None

    async def health_check(self) -> bool:
        """健康检查 - 验证配置和客户端可用。"""
        if self.config is None or self.client is None:
            return False
        errors = self.config.validate()
        return len(errors) == 0

    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理事件。"""
        if event == "webhook.received":
            return await self._handle_webhook(data)
        return {"status": "ignored", "event": event}

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行任务。"""
        if task == "create_comment":
            repo = params.get("repo", "")
            issue_number = params.get("issue_number", 0)
            body = params.get("body", "")
            result = await self.client.create_comment(repo, issue_number, body)
            return {"status": "ok", "task": task, "result": result}

        elif task == "update_comment":
            repo = params.get("repo", "")
            comment_id = params.get("comment_id", 0)
            body = params.get("body", "")
            result = await self.client.update_comment(repo, comment_id, body)
            return {"status": "ok", "task": task, "result": result}

        elif task == "get_comment":
            result = await self.client.get_comment(
                params.get("repo", ""), int(params.get("comment_id", 0))
            )
            return {"status": "ok", "task": task, "result": result}

        elif task == "delete_comment":
            await self.client.delete_comment(
                params.get("repo", ""), int(params.get("comment_id", 0))
            )
            return {"status": "ok", "task": task}

        elif task == "add_labels":
            repo = params.get("repo", "")
            issue_number = params.get("issue_number", 0)
            labels = params.get("labels", [])
            result = await self.client.add_labels(repo, issue_number, labels)
            return {"status": "ok", "task": task, "result": result}

        return {"status": "error", "message": f"Unknown task: {task}"}

    # -- 变更单元:效果提供者 --------------------------------------

    def effects(self) -> Dict[str, Any]:
        raw = yaml.safe_load(
            (Path(__file__).parent / "plugin.yaml").read_text(encoding="utf-8")
        )
        return dict(raw.get("effects") or {})

    def effect(self, name: str, **args: Any) -> Effect:
        raw = self.effects()[name]
        return Effect(
            task=raw["execute"]["task"],
            args=args,
            undo_task=raw["undo"]["task"],
            undo_kind=raw["undo"].get("kind", "retained"),
            label=raw.get("label", ""),
            capability=name,
        )

    async def execute(self, task: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """执行效果:返回句柄(评论 ID),撤销靠它定位。"""
        if task == "create_comment":
            result = await self.client.create_comment(
                args["repo"], int(args["issue_number"]), args["body"]
            )
            return {"handle": str(result["id"]), "url": result.get("html_url", "")}
        return await self.execute_task(task, args)

    async def undo(self, task: str, args: Dict[str, Any], handle: str) -> Dict[str, Any]:
        if task == "delete_comment":
            await self.client.delete_comment(args["repo"], int(handle))
            return {"deleted": handle}
        return await self.execute_task(task, {"handle": handle})

    async def window(self, effect: Effect, handle: str | None) -> Window:
        if self.client is None:
            return Window(source="client 未就绪")
        return Window(unbounded=True, source="comment_present")

    async def verify(self, effect: Effect, handle: str) -> tuple[bool, Dict[str, Any]]:
        data = await self.client.get_comment(effect.args["repo"], int(handle))
        return data is not None, {"comment_id": int(handle), "found": data is not None}

    async def _handle_webhook(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理 Webhook 事件。"""
        try:
            headers = data.get("headers", {})
            body = data.get("body", b"")

            # 验证签名（如果配置了 webhook_secret）
            signature = headers.get("X-Hub-Signature-256", "")
            if self.config.webhook_secret and not self.webhook_handler.verify_signature(body, signature):
                return {"status": "error", "message": "Invalid webhook signature"}

            # 解析事件
            event = self.webhook_handler.parse_event(headers, body)
            if event is None:
                return {"status": "ignored", "message": "Unsupported event type"}

            # 处理 ping 事件
            if event["type"] == "ping":
                return {"status": "ok", "message": "pong"}

            # 提取 issue 信息
            issue_info = self.webhook_handler.extract_issue_info(event)
            if issue_info is None:
                return {"status": "ignored", "message": "Could not extract issue info"}

            return {
                "status": "ok",
                "event_type": event["type"],
                "action": event["action"],
                "issue_info": issue_info,
            }
        except Exception as e:
            return {"status": "error", "message": f"Webhook 处理失败: {e}"}
