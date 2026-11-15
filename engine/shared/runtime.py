# engine/shared/runtime.py
"""插件运行时单例 —— 供 webhook 路由与工作流管道共用。

优先从插件注册表按名字取实例;注册表未加载(如单测直接导入)时回退到
旧直连单例,保持既有测试与调用点零改动。
"""

import logging

logger = logging.getLogger(__name__)

_sensor_instance = None


def _from_registry(name: str):
    try:
        from engine.plugin_manager import registry

        return registry.get(name)
    except Exception:
        return None


def get_adapter(source: str):
    """按来源取适配器(github / gitlab / cnb ...)。

    每个来源只有一个适配器,由它自己声明 `source`。取不到就抛 `LookupError` ——
    上一版这里写死返回 GitHub App 适配器,CNB 的投递进来会拿 GitHub 的身份去
    拉快照、问分支、发评论;错目标比报错糟。
    """
    from engine.ingest.source import source_adapter

    return source_adapter(source)


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
