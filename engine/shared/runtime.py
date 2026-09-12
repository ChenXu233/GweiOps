# engine/shared/runtime.py
"""插件运行时单例 — 供 webhook 路由与工作流管道共用。

优先从插件注册表按名字取实例;注册表未加载(如单测直接导入)时回退到
旧直连单例,保持既有测试与调用点零改动。
"""

import logging

logger = logging.getLogger(__name__)

_adapter_instance = None
_sensor_instance = None


def _from_registry(name: str):
    try:
        from engine.plugin_manager import registry

        return registry.get(name)
    except Exception:
        return None


def get_adapter():
    """获取 GitHubAppAdapter 实例（延迟导入避免循环依赖）。"""
    global _adapter_instance

    from_registry = _from_registry("github-app-adapter")
    if from_registry is not None:
        return from_registry

    if _adapter_instance is None:
        import importlib
        module = importlib.import_module("plugins.builtin.adapters.github-app.plugin")
        _adapter_instance = module.GitHubAppAdapter()
    return _adapter_instance


def get_sensor():
    """获取 SensorAgent 实例（延迟导入避免循环依赖）。"""
    global _sensor_instance

    from_registry = _from_registry("sensor-agent")
    if from_registry is not None:
        return from_registry

    if _sensor_instance is None:
        from plugins.builtin.agents.sensor.plugin import SensorAgent
        _sensor_instance = SensorAgent()
    return _sensor_instance
