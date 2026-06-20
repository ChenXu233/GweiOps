# plugins/builtin/adapters/github/plugin.py
from typing import Dict, Any
import sys
import os

# 添加 engine 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'engine'))

from plugin_manager.base import PluginBase, PluginInfo, PluginType
from .client import GitHubClient
from .git import GitTool


class GitHubAdapter(PluginBase):
    """GitHub 适配器插件"""

    def __init__(self):
        self.client: GitHubClient = None
        self.git_tool: GitTool = None
        self.config: Dict[str, Any] = {}

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="github-adapter",
            version="1.0.0",
            type=PluginType.ADAPTER,
            description="GitHub 托管适配器",
            triggers=[
                {
                    "type": "event",
                    "events": ["webhook.received", "issue.created", "pr.merged"],
                }
            ],
            capabilities=[
                "issue.read", "issue.write",
                "pr.read", "pr.write", "pr.merge",
                "comment.read", "comment.write",
                "webhook.receive",
            ],
            config={
                "required": ["GITHUB_TOKEN", "GITHUB_WEBHOOK_SECRET"],
                "optional": ["GITHUB_API_URL"],
            },
        )

    async def on_startup(self):
        """启动时初始化"""
        self.client = GitHubClient()
        self.git_tool = GitTool()

    async def on_shutdown(self):
        """关闭时释放资源"""
        self.client = None
        self.git_tool = None

    async def health_check(self) -> bool:
        """健康检查"""
        return self.client is not None

    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理事件"""
        if event == "webhook.received":
            return await self._handle_webhook(data)
        elif event == "issue.created":
            return await self._handle_issue_created(data)
        elif event == "pr.merged":
            return await self._handle_pr_merged(data)
        return {"status": "ignored", "event": event}

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行任务"""
        if task == "create_comment":
            return await self.client.create_comment(**params)
        elif task == "create_pr":
            return await self.client.create_pr(**params)
        elif task == "merge_pr":
            return await self.client.merge_pr(**params)
        return {"status": "error", "message": f"Unknown task: {task}"}

    async def _handle_webhook(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理 Webhook"""
        from .handlers import process_issue_event
        event_type = data.get("event_type", "")
        payload = data.get("payload", {})
        return await process_issue_event(event_type, payload)

    async def _handle_issue_created(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理 Issue 创建"""
        return {"status": "ok", "action": "issue_created"}

    async def _handle_pr_merged(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理 PR 合并"""
        return {"status": "ok", "action": "pr_merged"}
