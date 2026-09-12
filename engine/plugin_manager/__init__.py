# engine/plugin_manager/__init__.py
from .base import PluginBase, PluginInfo, PluginType
from .manifest import HookSubscription, Manifest, ManifestError
from .registry import PluginRegistry, registry
from .events import EventBus
from .hooks import HookPipeline

# 生产单例:事件总线与 Hook 管线共享同一注册表
events = EventBus(registry)
hooks = HookPipeline(registry)

__all__ = [
    "PluginBase",
    "PluginInfo",
    "PluginType",
    "Manifest",
    "ManifestError",
    "HookSubscription",
    "PluginRegistry",
    "registry",
    "EventBus",
    "events",
    "HookPipeline",
    "hooks",
]
