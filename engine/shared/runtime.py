# engine/shared/runtime.py
"""插件运行时单例 —— 供 webhook 路由与工作流管道共用。

取插件只有一条路:注册表。**没有直连兜底。**

以前这里写着"注册表未加载时回退到旧直连单例"。那个兜底让两个开关变成装饰:
`PLUGINS_DISABLED=sensor-agent` 之后,工作流照样直连 `SensorAgent` 把活干完;
日志里一句 INFO 都不会多。开关看着存在、其实不存在,比没有开关更费解。

现在分两种"取不到",各自的处理不同:

- **注册表还没跑过发现**(单测直接导入、引擎还没起来):这是"还没查",返回
  `None` 或抛 `LookupError`,调用方如实报告没开工——不拿一个临时对象假装插件在;
- **跑过发现但没这个插件**(没装、被停用、白名单没列):这是部署事实,同样抛,
  日志点名是哪个插件,让人知道去开什么。
"""

import logging

logger = logging.getLogger(__name__)


def _registry():
    from engine.plugin_manager import registry

    return registry


def get_adapter(source: str):
    """按来源取适配器(github / gitlab / cnb ...)。

    每个来源只有一个适配器,由它自己声明 `source`。取不到就抛 `LookupError` ——
    上一版这里写死返回 GitHub App 适配器,CNB 的投递进来会拿 GitHub 的身份去
    拉快照、问分支、发评论;错目标比报错糟。
    """
    from engine.ingest.source import source_adapter

    return source_adapter(source)


def get_sensor():
    """取 sense 能力的提供者。

    **没有直连兜底**:这个部署没启用 sensor-agent,就没有感知这一步。工作流会
    如实返回"没做感知",而不是偷偷用一个临时实例把活干完——那样 PLUGINS_DISABLED
    对主链路是装饰,人以为自己关掉了,实际上什么都没关掉。
    """
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
    """取修复智能体。与 get_sensor 同一条规矩:取不到就是没这个能力。"""
    registry = _registry()
    instance = registry.get("fixer-agent")
    if instance is not None:
        return instance
    if not registry.is_loaded():
        raise LookupError(
            "插件注册表还没发现过任何插件:先 registry.discover() 再取 fixer-agent"
        )
    raise LookupError(
        "这个部署没有启用 fixer-agent:补丁生成这一步没有提供者,"
        "检查 PLUGINS_ENABLED / PLUGINS_DISABLED,或在控制台的插件页把它打开"
    )
