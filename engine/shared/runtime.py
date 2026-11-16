# engine/shared/runtime.py
"""插件运行时单例 —— 供 webhook 路由与工作流管道共用。

取插件只有一条路:注册表,没有直连兜底。两种"取不到"各自处理:

- 注册表还没跑过发现(单测直接导入、引擎还没起来):抛 `LookupError`,说明"还没查";
- 跑过发现但注册表里没有目标插件(没装、被停用、白名单没列):同样抛,日志点名插件名。
"""

import logging

logger = logging.getLogger(__name__)


def _registry():
    from engine.plugin_manager import registry

    return registry


def get_adapter(source: str):
    """按来源取适配器(github / gitlab / cnb ...)。

    每个来源只有一个适配器,由它自己声明 `source`。取不到就抛 `LookupError`。
    """
    from engine.ingest.source import source_adapter

    return source_adapter(source)


def get_sensor():
    """取 sense 能力的提供者;没有直连兜底,未启用就没有感知步骤。"""
    registry = _registry()
    instance = registry.get("sensor-agent")
    if instance is not None:
        return instance
    if not registry.is_loaded():
        raise LookupError(
            "插件注册表还没发现过任何插件:先 registry.discover() 再取 sensor-agent"
        )
    raise LookupError(
        "这个部署没有启用 sensor-agent:检查 PLUGINS_ENABLED / PLUGINS_DISABLED "
        "与清单里的 default_enabled,或在控制台的插件页把它打开"
    )


def get_fixer():
    """取修复智能体。与 `get_sensor` 同一规矩:取不到就是没这个能力。"""
    registry = _registry()
    instance = registry.get("fixer-agent")
    if instance is not None:
        return instance
    if not registry.is_loaded():
        raise LookupError(
            "插件注册表还没发现过任何插件:先 registry.discover() 再取 fixer-agent"
        )
    raise LookupError(
        "这个部署没有启用 fixer-agent:补丁生成没有提供者,"
        "检查 PLUGINS_ENABLED / PLUGINS_DISABLED,或在控制台的插件页把它打开"
    )
