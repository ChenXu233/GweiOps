from typing import Dict, Any
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'engine'))

from plugin_manager.base import PluginBase, PluginInfo, PluginType
from .analyzer import CodeAnalyzer
from .locator import BugReproducer


class DiagnoserAgent(PluginBase):
    """诊断智能体"""

    def __init__(self):
        self.analyzer = CodeAnalyzer()
        self.reproducer = BugReproducer()

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="diagnoser-agent",
            version="1.0.0",
            type=PluginType.AGENT,
            description="诊断智能体，分析问题根因",
            triggers=[
                {"type": "event", "events": ["issue.labeled", "sensor.processed"]},
            ],
            capabilities=["issue.analyze", "code.analyze", "bug.reproduce"],
        )

    async def on_startup(self):
        pass

    async def on_shutdown(self):
        pass

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if event in ("issue.labeled", "sensor.processed"):
            return await self._diagnose(data)
        return {"status": "ignored"}

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if task == "analyze_code":
            result = self.analyzer.analyze(params.get("code", ""), params.get("language", "python"))
            return {
                "functions": result.functions,
                "classes": result.classes,
                "methods": result.methods,
                "imports": result.imports,
                "has_syntax_error": result.has_syntax_error,
            }
        elif task == "reproduce":
            result = await self.reproducer.reproduce(
                repo_url=params.get("repo_url", ""),
                issue_number=params.get("issue_number", 0),
                steps=params.get("steps", []),
            )
            return {
                "success": result.success,
                "error_output": result.error_output,
                "stack_trace": result.stack_trace,
            }
        return {"status": "error", "message": f"Unknown task: {task}"}

    async def _diagnose(self, data: Dict[str, Any]) -> Dict[str, Any]:
        issue = data.get("issue", {})
        code = issue.get("code", "")
        language = issue.get("language", "python")

        analysis = self.analyzer.analyze(code, language)

        return {
            "status": "ok",
            "functions": analysis.functions,
            "classes": analysis.classes,
            "has_syntax_error": analysis.has_syntax_error,
            "error_message": analysis.error_message,
        }
