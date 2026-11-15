# engine/quota/__init__.py
"""配额:限量怎么声明、用量怎么算、超了怎么说话。

现在落地的是**账本与判定**:一个租户(或一个人)在某个资源上的限量写进配置,
用量的每一笔落进 `quota_usage`,判定读窗口内的和。

还没落地的是**执行点**:真去拦下一个工作流的入口。那件事在工作分解 §6.1,
这里只把形状先定下来 —— 先把"某租户配额调到 0"这件事说清楚,再决定在哪个入口拦。

三条约定:

- **没声明限量 = 不限**。配额是加购项,不是默认的门。
- **窗口是滚动的**,`5h` / `7d` / `30d`;不认识的时间单位当场报错,不悄悄当成不限。
- **判定要说出是哪个资源、窗口多少、用掉多少、上限多少**。只回一句"超了",
  运维还得自己去猜是哪一个。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from engine.shared.config import config

UNIT_HOURS = {"h": 1, "d": 24, "w": 24 * 7}

# 默认限量:一个自部署实例够用,但不会让人一晚上把整月额度打光。
DEFAULT_LIMITS: dict[str, str] = {
    "issues": "2000/30d",
    "llm_tokens": "2000000/30d",
    "agent_runs": "500/5h",
}

_WINDOW = re.compile(r"^(\d+)([hdw])$")


class QuotaError(ValueError):
    """限量写法不对。写入时就该报,不等到第一次判定。"""


@dataclass(frozen=True)
class Limit:
    """`2000/30d` 拆开的样子。window_hours=0 表示不限。"""

    resource: str
    amount: int
    window_hours: int

    def describe(self) -> str:
        return f"{self.amount}/{self.window_hours}h" if self.window_hours else "不限"

    def window(self, now: datetime | None = None) -> datetime | None:
        if not self.window_hours:
            return None
        return (now or datetime.now(timezone.utc)) - timedelta(hours=self.window_hours)


def parse_limit(resource: str, raw: str) -> Limit:
    """`2000/30d` → Limit。空值 = 不限。写错就报,不猜。"""
    spec = (raw or "").strip()
    if not spec:
        return Limit(resource=resource, amount=0, window_hours=0)
    if "/" not in spec:
        raise QuotaError(f"{resource} 的限量要写成 数量/窗口,例如 2000/30d,收到 {raw!r}")
    head, _, tail = spec.partition("/")
    try:
        amount = int(head.strip())
    except ValueError:
        raise QuotaError(f"{resource} 的数量不是整数:{head!r}") from None
    if amount < 0:
        raise QuotaError(f"{resource} 的数量不能是负数:{amount}")
    matched = _WINDOW.match(tail.strip().lower())
    if matched is None:
        raise QuotaError(f"{resource} 的窗口只认 数字h/d/w,收到 {tail!r}")
    return Limit(
        resource=resource,
        amount=amount,
        window_hours=int(matched.group(1)) * UNIT_HOURS[matched.group(2)],
    )


def limits_for(tenant: str = "") -> dict[str, Limit]:
    """一个租户现在的限量:平台默认 → 公共配置 → 租户配置,后者覆盖前者。

    键名照配额表的写法:`ISSUES=2000/30d,AGENT_RUNS=100/5h`。
    """
    merged = dict(DEFAULT_LIMITS)
    # stored 已经把公共那份打底、租户那份覆盖,取一次就够
    for layer in (config.stored("quota", tenant),):
        for key, value in layer.items():
            if value is None:
                continue
            merged[key.strip().lower()] = value
    return {name: parse_limit(name, raw) for name, raw in merged.items()}


__all__ = ["DEFAULT_LIMITS", "Limit", "QuotaError", "limits_for", "parse_limit"]
