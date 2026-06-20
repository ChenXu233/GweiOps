from typing import Dict, Any
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'engine'))

from plugin_manager.base import PluginBase, PluginInfo, PluginType
from .labeler import LabelGenerator
from .completeness import CompletenessChecker
from .duplicate import DuplicateDetector


class SensorAgent(PluginBase):
    """感知智能体"""

    def __init__(self):
        self.labeler = LabelGenerator()
        self.completeness = CompletenessChecker()
        self.duplicate = DuplicateDetector()

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="sensor-agent",
            version="1.0.0",
            type=PluginType.AGENT,
            description="感知智能体，监听事件",
            triggers=[
                {"type": "event", "events": ["webhook.received", "issue.created"]},
            ],
            capabilities=["issue.label", "issue.completeness_check", "issue.duplicate_detection"],
        )

    async def on_startup(self):
        pass

    async def on_shutdown(self):
        pass

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if event in ("webhook.received", "issue.created"):
            return await self._process_issue(data)
        return {"status": "ignored"}

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if task == "label":
            labels = self.labeler.generate(params.get("title", ""), params.get("body", ""))
            return {"labels": labels}
        elif task == "check_completeness":
            report = self.completeness.check(params.get("body", ""))
            return {"is_complete": report.is_complete, "missing": report.missing_fields}
        return {"status": "error", "message": f"Unknown task: {task}"}

    async def _process_issue(self, data: Dict[str, Any]) -> Dict[str, Any]:
        issue = data.get("issue", {})
        title = issue.get("title", "")
        body = issue.get("body", "")

        labels = self.labeler.generate(title, body)
        completeness = self.completeness.check(body)

        return {
            "status": "ok",
            "labels": labels,
            "is_complete": completeness.is_complete,
            "missing_fields": completeness.missing_fields,
        }
