from typing import Dict, Any
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'engine'))

from plugin_manager.base import PluginBase, PluginInfo, PluginType


class ObserverAgent(PluginBase):
    """观察智能体"""

    def __init__(self):
        self._metrics: Dict[str, Any] = {}

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="observer-agent",
            version="1.0.0",
            type=PluginType.AGENT,
            description="观察智能体，监控系统状态",
            triggers=[
                {"type": "schedule", "interval": "60s"},
            ],
            capabilities=["system.monitor", "metrics.collect"],
        )

    async def on_startup(self):
        pass

    async def on_shutdown(self):
        self._metrics.clear()

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "ok", "metrics": self._metrics}

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if task == "collect_metrics":
            return {"status": "ok", "metrics": self._metrics}
        elif task == "record_metric":
            name = params.get("name", "")
            value = params.get("value")
            if name:
                self._metrics[name] = value
                return {"status": "ok"}
            return {"status": "error", "message": "Missing metric name"}
        return {"status": "error", "message": f"Unknown task: {task}"}
