# engine/plugin_manager/events.py
"""进程内事件总线 —— 插件事件订阅的执行器。

语义:**best-effort**。总线只做进程内 fan-out,不提供投递保证、不重试、
不持久化——需要可靠执行的事件链路由 DBOS 工作流负责(见
engine/workflows/pipeline.py 的事件 step)。单订阅者超时或异常只影响自身,
不波及其他订阅者,也不影响发布方。
"""

import asyncio
import logging

from engine.shared.metrics import metrics

from .registry import PluginRegistry

logger = logging.getLogger(__name__)

DEFAULT_HANDLER_TIMEOUT_S = 10.0


class EventBus:
    def __init__(self, registry: PluginRegistry, timeout_s: float = DEFAULT_HANDLER_TIMEOUT_S):
        self._registry = registry
        self._timeout_s = timeout_s

    async def publish(self, event: str, payload: dict) -> int:
        """向事件订阅者 fan-out,返回成功处理的订阅者数量。"""
        metrics.increment("plugin_events_published_total", {"event": event})
        subscribers = self._registry.instances_for_event(event)
        completed = 0
        for instance in subscribers:
            name = type(instance).__name__
            try:
                await asyncio.wait_for(
                    instance.handle_event(event, payload), timeout=self._timeout_s
                )
                completed += 1
            except asyncio.TimeoutError:
                metrics.increment(
                    "plugin_event_handler_errors_total", {"plugin": name, "kind": "timeout"}
                )
                logger.warning("Event handler timeout: plugin=%s event=%s", name, event)
            except Exception as e:
                metrics.increment(
                    "plugin_event_handler_errors_total", {"plugin": name, "kind": "error"}
                )
                logger.error("Event handler failed: plugin=%s event=%s: %s", name, event, e)
        return completed
