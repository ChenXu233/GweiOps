from typing import Dict, Any, List
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'engine'))

from plugin_manager.base import PluginBase, PluginInfo, PluginType


class LearnerAgent(PluginBase):
    """学习智能体"""

    def __init__(self):
        self._patterns: List[Dict[str, Any]] = []

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="learner-agent",
            version="1.0.0",
            type=PluginType.AGENT,
            description="学习智能体，从历史数据中学习",
            triggers=[
                {"type": "event", "events": ["workflow.completed", "pr.merged"]},
            ],
            capabilities=["knowledge.extract", "pattern.learn"],
        )

    async def on_startup(self):
        pass

    async def on_shutdown(self):
        self._patterns.clear()

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if event in ("workflow.completed", "pr.merged"):
            return await self._learn(data)
        return {"status": "ignored"}

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if task == "extract_knowledge":
            pattern = {
                "type": params.get("type", "unknown"),
                "context": params.get("context", ""),
                "outcome": params.get("outcome", ""),
            }
            self._patterns.append(pattern)
            return {"status": "ok", "pattern_count": len(self._patterns)}
        elif task == "get_patterns":
            return {"status": "ok", "patterns": self._patterns}
        return {"status": "error", "message": f"Unknown task: {task}"}

    async def _learn(self, data: Dict[str, Any]) -> Dict[str, Any]:
        pattern = {
            "type": data.get("type", "unknown"),
            "context": data.get("context", ""),
            "outcome": data.get("outcome", ""),
        }
        self._patterns.append(pattern)
        return {"status": "ok", "pattern_count": len(self._patterns)}
