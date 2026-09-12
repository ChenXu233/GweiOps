# engine/shared/runtime.py
"""插件运行时单例 — 供 webhook 路由与工作流管道共用。

原逻辑位于 engine/api/routes/webhook.py;抽到此模块以避免
webhook → pipeline → webhook 的循环导入。
"""

import logging

logger = logging.getLogger(__name__)

_adapter_instance = None
_sensor_instance = None


def get_adapter():
    """获取 GitHubAppAdapter 实例（延迟导入避免循环依赖）。"""
    global _adapter_instance
    if _adapter_instance is None:
        import importlib
        module = importlib.import_module("plugins.builtin.adapters.github-app.plugin")
        _adapter_instance = module.GitHubAppAdapter()
    return _adapter_instance


def get_sensor():
    """获取 SensorAgent 实例（延迟导入避免循环依赖）。"""
    global _sensor_instance
    if _sensor_instance is None:
        from plugins.builtin.agents.sensor.plugin import SensorAgent
        _sensor_instance = SensorAgent()
    return _sensor_instance
