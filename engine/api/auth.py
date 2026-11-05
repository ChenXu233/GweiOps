# engine/api/auth.py
"""控制台令牌 —— 让"谁在调用"变成事实,而不是请求里的人自己写的备注。

在这之前,by 与 tenant 全靠调用方声明。那不是鉴权,是留言:任何人都能说
自己是别人、要看别人的账。

这里做最小的一件事:一个令牌声明它是谁、属于哪个租户、能做什么。
租户只能看自己的账;改变世界的请求要 operate。

没有配置令牌时不鉴权——这句话必须能被看见,所以每个响应都带 `X-Gwei-Auth: on|off`。
单机自用可以这样跑;SaaS 必须配上。

令牌格式:`token:tenant:actor:scope`,逗号分隔多条。tenant 写 `*` 表示不限租户
(运维令牌),scope 取 `read` 或 `operate`。令牌本身不能含冒号。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
SCOPES = ("read", "operate")

# 健康检查要能在没有令牌时访问:它是不带数据的存活探测。
EXEMPT_PATHS = frozenset({"/api/health", "/openapi.json", "/docs", "/redoc"})
EXEMPT_PREFIXES = ("/webhook/",)  # 每个 webhook 自带共享密钥,不走这套
TOKEN_HEADER = "x-gwei-token"
AUTH_HEADER = "X-Gwei-Auth"


@dataclass(frozen=True)
class Actor:
    """一次请求的身份。token_id 只用于日志,不回显。"""

    token_id: str
    name: str
    tenant: str = ""  # "" = 不限租户
    scope: str = "read"

    def __repr__(self) -> str:  # 别把令牌打进日志
        return f"Actor(name={self.name!r}, tenant={self.tenant!r}, scope={self.scope!r})"


class TokenConfigError(ValueError):
    """令牌配置写错。启动即报错——写错的令牌不能静默降级成"不鉴权"。"""


def load_tokens(raw: str) -> dict[str, Actor]:
    """解析 `token:tenant:actor:scope` 列表。任何一行写错都拒绝启动。"""
    out: dict[str, Actor] = {}
    for line in (raw or "").split(","):
        entry = line.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) != 4:
            raise TokenConfigError(
                f"令牌条目格式应为 token:tenant:actor:scope,收到 {len(parts)} 段"
            )
        token_id, tenant, name, scope = (part.strip() for part in parts)
        if not token_id:
            raise TokenConfigError("令牌不能为空")
        if scope not in SCOPES:
            raise TokenConfigError(f"scope 只能是 {'/'.join(SCOPES)},收到 {scope!r}")
        if token_id in out:
            raise TokenConfigError("令牌重复")
        out[token_id] = Actor(
            token_id=token_id,
            name=name or "未具名",
            tenant="" if tenant == "*" else tenant,
            scope=scope,
        )
    return out


def make_middleware(tokens: dict[str, Actor]) -> Callable[..., Any]:
    """挂到 app 上的鉴权中间件。tokens 为空时不鉴权,但会明说。"""

    async def middleware(request: Request, call_next):
        request.state.actor = None
        path = request.url.path
        guarded = bool(tokens) and path.startswith("/api/") and path not in EXEMPT_PATHS

        if guarded:
            actor = tokens.get((request.headers.get(TOKEN_HEADER) or "").strip())
            if actor is None:
                return JSONResponse(
                    {"detail": "缺少或无效的控制台令牌"}, status_code=401
                )
            if request.method not in SAFE_METHODS and actor.scope != "operate":
                return JSONResponse(
                    {"detail": f"这个令牌只读,不能 {request.method}"}, status_code=403
                )
            request.state.actor = actor

        response = await call_next(request)
        response.headers[AUTH_HEADER] = "on" if tokens else "off"
        return response

    return middleware


def actor_of(request: Request) -> Actor | None:
    return getattr(request.state, "actor", None)


def tenant_scope(request: Request, requested: str | None) -> str | None:
    """令牌声明的租户优先于查询参数;两者不一致是越权,不是覆盖。"""
    actor = actor_of(request)
    if actor is None or not actor.tenant:
        return requested
    if requested and requested != actor.tenant:
        raise HTTPException(status_code=403, detail="这个令牌看不到该租户的账")
    return actor.tenant


def by_of(request: Request, declared: str) -> str:
    """谁做的这件事。有令牌时以令牌为准,请求里写的只是它在没有鉴权时的替代品。"""
    actor = actor_of(request)
    return actor.name if actor else declared


__all__ = [
    "Actor",
    "TokenConfigError",
    "load_tokens",
    "make_middleware",
    "actor_of",
    "tenant_scope",
    "by_of",
    "TOKEN_HEADER",
    "AUTH_HEADER",
]
