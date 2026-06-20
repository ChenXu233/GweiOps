# engine/plugin_manager/dispatcher.py
from typing import Dict, Any, List
from .base import PluginBase, PluginInfo


class PluginDispatcher:
    """插件调度器，负责事件分发和任务调度"""

    def __init__(self):
        self.plugins: Dict[str, PluginBase] = {}
        self.event_handlers: Dict[str, List[str]] = {}
        self.scheduler_handlers: Dict[str, List[str]] = {}

    def register(self, plugin: PluginBase):
        """注册插件"""
        info = plugin.info()
        name = info.name
        self.plugins[name] = plugin

        # 索引事件触发
        for trigger in info.triggers:
            if trigger["type"] == "event":
                for event in trigger["events"]:
                    if event not in self.event_handlers:
                        self.event_handlers[event] = []
                    self.event_handlers[event].append(name)

            elif trigger["type"] == "scheduler":
                for state in trigger["states"]:
                    if state not in self.scheduler_handlers:
                        self.scheduler_handlers[state] = []
                    self.scheduler_handlers[state].append(name)

    def unregister(self, name: str):
        """注销插件"""
        if name in self.plugins:
            del self.plugins[name]

            # 清理索引
            for event, handlers in self.event_handlers.items():
                if name in handlers:
                    handlers.remove(name)

            for state, handlers in self.scheduler_handlers.items():
                if name in handlers:
                    handlers.remove(name)

    async def dispatch_event(self, event: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """事件触发分发"""
        results = []
        plugin_names = self.event_handlers.get(event, [])

        for name in plugin_names:
            if name in self.plugins:
                plugin = self.plugins[name]
                try:
                    result = await plugin.handle_event(event, data)
                    results.append({"plugin": name, "success": True, "result": result})
                except Exception as e:
                    results.append({"plugin": name, "success": False, "error": str(e)})

        return results

    async def dispatch_task(self, state: str, task: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """调度智能体触发分发"""
        results = []
        plugin_names = self.scheduler_handlers.get(state, [])

        for name in plugin_names:
            if name in self.plugins:
                plugin = self.plugins[name]
                try:
                    result = await plugin.execute_task(task, params)
                    results.append({"plugin": name, "success": True, "result": result})
                except Exception as e:
                    results.append({"plugin": name, "success": False, "error": str(e)})

        return results

    async def health_check_all(self) -> Dict[str, bool]:
        """检查所有插件健康状态"""
        results = {}
        for name, plugin in self.plugins.items():
            try:
                results[name] = await plugin.health_check()
            except Exception:
                results[name] = False
        return results

    def list_plugins(self) -> List[PluginInfo]:
        """列出所有插件"""
        return [plugin.info() for plugin in self.plugins.values()]
