# engine/plugin_manager/enablement.py
"""插件的启停决定存在哪 —— 让"打开一个插件"活过重启。

决定只有两种:开、关。它不是插件配置(那是 scope 里的事),所以单独占一个
`plugin-enablement` scope:键是插件名,值是 `on` / `off`。

优先级:这里的决定 > `PLUGINS_ENABLED` 白名单 > `PLUGINS_DISABLED` > 清单
`default_enabled`。人在控制台上点过的开关,应当压过部署时写的一行环境变量——
否则"关掉一个插件"在下次滚动重启后就悄悄反弹回来,而没人记得为什么。
"""

from __future__ import annotations

import logging

from engine.shared.settings_store import create_settings_store

logger = logging.getLogger(__name__)

SCOPE = "plugin-enablement"


async def load_decisions(tenant: str = "") -> dict[str, bool]:
    """读回全部启停决定。读不到就当一条都没有——用清单默认值,不是当全关。"""
    try:
        stored = await create_settings_store().load()
    except Exception:  # noqa: BLE001 - 库没起来时不该让引擎也起不来
        logger.warning("读不到插件的启停决定,这次按清单默认", exc_info=True)
        return {}
    merged = dict(stored.get("", {}).get(SCOPE, {}))
    if tenant:
        merged.update(stored.get(tenant, {}).get(SCOPE, {}))
    out: dict[str, bool] = {}
    for name, value in merged.items():
        text = str(value).strip().lower()
        if text in ("on", "true", "1", "yes"):
            out[name] = True
        elif text in ("off", "false", "0", "no"):
            out[name] = False
    return out


async def save_decision(name: str, enabled: bool, *, by: str = "", tenant: str = "") -> None:
    """写一条决定。写不进去就抛——静默失败会让页面上的开关骗人。"""
    await create_settings_store().put(
        SCOPE, {name: "on" if enabled else "off"}, by=by, tenant=tenant
    )


__all__ = ["SCOPE", "load_decisions", "save_decision"]
