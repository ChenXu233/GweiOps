# plugins/builtin/adapters/github-app/plugin.py
"""GitHub App Adapter 插件 - 通过 GitHub App 进行交互。"""

from typing import Dict, Any

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
        self.webhook_handler = WebhookHandler()

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

        elif task == "add_labels":
            repo = params.get("repo", "")
            issue_number = params.get("issue_number", 0)
            labels = params.get("labels", [])
            result = await self.client.add_labels(repo, issue_number, labels)
            return {"status": "ok", "task": task, "result": result}

        return {"status": "error", "message": f"Unknown task: {task}"}

    async def _handle_webhook(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理 Webhook 事件。"""
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
