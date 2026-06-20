from typing import Dict, Any
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'engine'))

from plugin_manager.base import PluginBase, PluginInfo, PluginType
from .ci import PRCreator
from .cd import PRIterationService


class DeployerAgent(PluginBase):
    """部署智能体"""

    def __init__(self):
        self.pr_creator = PRCreator()
        self.pr_iteration = PRIterationService()

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="deployer-agent",
            version="1.0.0",
            type=PluginType.AGENT,
            description="部署智能体，创建 PR 并处理迭代",
            triggers=[
                {"type": "event", "events": ["fix.generated", "patch.approved"]},
            ],
            capabilities=["pr.create", "pr.iterate"],
        )

    async def on_startup(self):
        pass

    async def on_shutdown(self):
        pass

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if event in ("fix.generated", "patch.approved"):
            return await self._create_pr(data)
        return {"status": "ignored"}

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if task == "create_pr":
            result = await self.pr_creator.create(
                repo=params.get("repo", ""),
                title=params.get("title", ""),
                body=params.get("body", ""),
                head=params.get("head", ""),
                base=params.get("base", "main"),
            )
            return {
                "success": result.success,
                "pr_number": result.pr_number,
                "pr_url": result.pr_url,
            }
        elif task == "process_review":
            result = await self.pr_iteration.process_review_comment(
                pr_number=params.get("pr_number", 0),
                comment_body=params.get("comment", ""),
                commenter=params.get("commenter", ""),
            )
            return {
                "success": result.success,
                "action": result.action,
                "message": result.message,
            }
        return {"status": "error", "message": f"Unknown task: {task}"}

    async def _create_pr(self, data: Dict[str, Any]) -> Dict[str, Any]:
        result = await self.pr_creator.create(
            repo=data.get("repo", ""),
            title=data.get("title", "Auto-fix"),
            body=data.get("body", ""),
            head=data.get("head", ""),
            base=data.get("base", "main"),
        )

        return {
            "status": "ok",
            "success": result.success,
            "pr_number": result.pr_number,
            "pr_url": result.pr_url,
        }
