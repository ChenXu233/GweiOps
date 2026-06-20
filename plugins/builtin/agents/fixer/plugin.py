from typing import Dict, Any
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'engine'))

from plugin_manager.base import PluginBase, PluginInfo, PluginType
from .generator import PatchGenerator
from .reviewer import CodeReviewer


class FixerAgent(PluginBase):
    """修复智能体"""

    def __init__(self):
        self.patch_generator = PatchGenerator()
        self.reviewer = CodeReviewer()

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="fixer-agent",
            version="1.0.0",
            type=PluginType.AGENT,
            description="修复智能体，生成修复补丁",
            triggers=[
                {"type": "event", "events": ["diagnosis.complete", "issue.analyzed"]},
            ],
            capabilities=["patch.generate", "code.review"],
        )

    async def on_startup(self):
        pass

    async def on_shutdown(self):
        pass

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if event in ("diagnosis.complete", "issue.analyzed"):
            return await self._generate_fix(data)
        return {"status": "ignored"}

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if task == "generate_patches":
            patches = self.patch_generator.generate_all(
                issue_title=params.get("title", ""),
                issue_body=params.get("body", ""),
                file_path=params.get("file_path", ""),
            )
            return {
                "patches": [
                    {"type": p.type, "diff": p.diff, "risk": p.risk, "description": p.description}
                    for p in patches
                ]
            }
        elif task == "review_code":
            result = self.reviewer.review(params.get("code", ""), params.get("language", "python"))
            return {
                "score": result.score,
                "summary": result.summary,
                "issues": [{"severity": i.severity, "message": i.message, "line": i.line} for i in result.issues],
            }
        return {"status": "error", "message": f"Unknown task: {task}"}

    async def _generate_fix(self, data: Dict[str, Any]) -> Dict[str, Any]:
        issue = data.get("issue", {})
        title = issue.get("title", "")
        body = issue.get("body", "")
        file_path = data.get("file_path", "")

        patches = self.patch_generator.generate_all(title, body, file_path)

        return {
            "status": "ok",
            "patches": [
                {"type": p.type, "diff": p.diff, "risk": p.risk, "description": p.description}
                for p in patches
            ],
        }
