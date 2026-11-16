# engine/plugin_manager/enablement.py
"""插件的启停决定存在哪 —— 一个部署里有两层,不是一个开关。

**部署级(平台是否提供)**:`PLUGINS_ENABLED` / `PLUGINS_DISABLED` / 清单
`default_enabled`。它回答"这个部署里有没有这个东西",改它要改环境变量或清单。

**租户级(这个租户是否启用)**:存在 `plugin-tenancy` scope 里(见
`engine.plugin_manager.tenancy`)。它回答"在平台提供的范围里,这个租户选没选它"。

两层的关系是**取交集**,不是覆盖:

    真的在跑 = 平台提供了 且 租户启用了

所以租户只能在自己的集合里选,不能把平台关掉的插件打开——反过来也一样。
把两层压成一层(谁写了就算谁)会在 SaaS 上破:一个租户的开关会让所有租户都变。

`plugin-enablement` 这个 scope 是旧的单层决定,现在只用于"部署级"的显式覆盖
(控制面对 `tenant=""` 的写入),租户级的写入一律落 `plugin-tenancy`。
"""

from __future__ import annotations

import logging

from engine.shared.settings_store import create_settings_store

logger = logging.getLogger(__name__)

SCOPE = "plugin-enablement"


async def load_decisions(tenant: str = "") -> dict[str, bool]:
    """读回部署级的显式决定(公共值 + 该租户的旧覆盖)。

    新代码请用 `tenancy.load_tenancy(tenant)` 取租户级决定;这里保留是因为
    "部署级显式覆盖"仍然需要一个地方存,而且老库里的行还得读得出来。
    """
    try:
        stored = await create_settings_store().load()
    except Exception:  # noqa: BLE001 - 库没起来时按无决定处理
        logger.warning("读不到插件的启停决定,这次按清单默认", exc_info=True)
        return {}
    merged = dict(stored.get("", {}).get(SCOPE, {}))
    if tenant:
        merged.update(stored.get(tenant, {}).get(SCOPE, {}))
    return _as_bools(merged)


async def save_decision(name: str, enabled: bool, *, by: str = "", tenant: str = "") -> None:
    """写一条部署级决定;写不进去就抛,不静默失败。"""
    await create_settings_store().put(
        SCOPE, {name: "on" if enabled else "off"}, by=by, tenant=tenant
    )


def _as_bools(values: dict[str, str]) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for name, value in values.items():
        text = str(value).strip().lower()
        if text in ("on", "true", "1", "yes"):
            out[name] = True
        elif text in ("off", "false", "0", "no"):
            out[name] = False
    return out


__all__ = ["SCOPE", "load_decisions", "save_decision"]
