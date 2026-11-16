# engine/plugin_manager/enablement.py
"""插件的启停决定存在哪 —— 让"打开一个插件"活过重启。

决定只有两种:开、关,单独占一个 `plugin-enablement` scope:键是插件名,
值是 `on` / `off`。优先级:这里的决定 > `PLUGINS_ENABLED` 白名单 >
`PLUGINS_DISABLED` > 清单 `default_enabled`。
"""

from __future__ import annotations

import logging

from engine.shared.settings_store import create_settings_store

logger = logging.getLogger(__name__)

SCOPE = "plugin-enablement"


async def load_decisions(tenant: str = "") -> dict[str, bool]:
    """读回全部启停决定;读不到就当一条没有,按清单默认值。"""
    try:
        stored = await create_settings_store().load()
    except Exception:  # noqa: BLE001 - 库没起来时按无决定处理
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
    """写一条决定;写不进去就抛,不静默失败。"""
    await create_settings_store().put(
        SCOPE, {name: "on" if enabled else "off"}, by=by, tenant=tenant
    )


__all__ = ["SCOPE", "load_decisions", "save_decision"]
