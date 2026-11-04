# engine/shared/netenv.py
"""环境变量里的网络设置做一次规范化。

httpx 会把 NO_PROXY 中 [::1] 这类带方括号的 IPv6 条目当成「主机:端口」解析,
抛 InvalidURL: Invalid port ':1]'。带方括号的写法对 curl 合法,对 httpx 不合法。
这里在创建客户端前去掉两端方括号(裸 ::1 同样能被正确匹配)。

作用于进程环境:httpx 在每次构造客户端时读取代理设置,规范化一次即可。
带端口的条目(如 [::1]:8080)保持原样——去掉方括号会得到歧义地址。
"""

from __future__ import annotations

import os

PROXY_VARS = ("NO_PROXY", "no_proxy")


def normalize_no_proxy(raw: str) -> str:
    """去掉 NO_PROXY 里 IPv6 条目的方括号,保留其余条目与顺序。"""
    items: list[str] = []
    for part in (raw or "").split(","):
        item = part.strip()
        if not item:
            continue
        if item.startswith("[") and item.endswith("]"):
            inner = item[1:-1]
            if inner and ":" in inner:
                items.append(inner)
                continue
        items.append(item)
    return ",".join(items)


def prepare_proxy_env() -> None:
    """就地规范化代理相关的环境变量;重复调用无副作用。"""
    for var in PROXY_VARS:
        raw = os.environ.get(var)
        if raw:
            os.environ[var] = normalize_no_proxy(raw)
