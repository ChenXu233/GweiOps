from typing import Dict, Any
from engine.plugin_manager.base import PluginBase


class ObserverAgent(PluginBase):
    """观察智能体"""

    def __init__(self):
        self._metrics: Dict[str, Any] = {}

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
