# engine/plugin_manager/hooks.py
"""Hook 管线 —— 系统与插件行为变更的唯一合法通道之一。

三档语义:
- observe:   只读旁听,handler 返回值丢弃;
- transform: 链式修改载荷,上一个订阅者的输出是下一个的输入;
- veto:      返回假值即否决当前操作,管线立即短路。

红线:平台执行点(租户隔离、认证、配额执行、DBOS 持久化语义)不设扩展点,
hooks 模块不提供这些位置的接线——插件可观察策略,不可绕过强制。

失败语义由订阅声明(failure_mode):
- fail_open:   handler 异常 → 记日志跳过,管线继续;
- fail_closed: handler 异常 → 视同为 veto(保守失败)。

所有 veto 均留审计:metrics 计数 + WARNING 日志含载荷摘要。
"""

import json
import logging
from typing import Any

from engine.shared.metrics import metrics

from .registry import PluginRegistry

logger = logging.getLogger(__name__)


def _summarize(payload: Any, limit: int = 200) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        text = repr(payload)
    return text[:limit]


class HookPipeline:
    def __init__(self, registry: PluginRegistry):
        self._registry = registry

    async def apply(self, point: str, payload: Any) -> dict:
        """执行扩展点上的全部订阅者。

        返回 {"allowed": bool, "payload": payload};veto 后 payload 为当前值,
        调用方必须尊重 allowed=False(例如放弃发评论)。
        """
        for manifest, instance, declaration in self._registry.hook_subscribers(point):
            handler = getattr(instance, declaration.handler, None)
            if handler is None or not callable(handler):
                continue
            try:
                result = await handler(point, payload)
            except Exception as e:
                if declaration.failure_mode == "fail_closed":
                    self._audit_veto(manifest.name, point, payload, reason=f"fail_closed: {e}")
                    return {"allowed": False, "payload": payload}
                logger.error(
                    "Hook handler failed (fail_open): plugin=%s point=%s: %s",
                    manifest.name,
                    point,
                    e,
                )
                continue

            if declaration.mode == "veto":
                if not result:
                    self._audit_veto(manifest.name, point, payload)
                    return {"allowed": False, "payload": payload}
            elif declaration.mode == "transform":
                if result is not None:
                    payload = result
            # observe: 结果丢弃

        return {"allowed": True, "payload": payload}

    @staticmethod
    def _audit_veto(plugin: str, point: str, payload: Any, reason: str = "") -> None:
        metrics.increment("plugin_hook_veto_total", {"plugin": plugin, "point": point})
        suffix = f" ({reason})" if reason else ""
        logger.warning(
            "Hook VETO: plugin=%s point=%s%s payload=%s",
            plugin,
            point,
            suffix,
            _summarize(payload),
        )
