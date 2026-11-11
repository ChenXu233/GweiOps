# engine/api/auth.py
"""谁在调用 —— 会话 cookie 给人,令牌给机器。

在这之前,by 与 tenant 全靠调用方声明。那不是鉴权,是留言:任何人都能说
自己是别人、要看别人的账。

现在有两套凭据,井水不犯河水:

- **人**:POST /api/auth/login 换成会话 cookie(HttpOnly),权限由角色算出来
- **机器**:X-Gwei-Token, `token:tenant:actor:scope`,给 harness 与 alertmanager 用

没有配置任何凭据时不鉴权——这句话必须能被看见,所以每个响应都带
X-Gwei-Auth: on|off。单机自用可以这样跑;放到公网必须配。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from engine.auth import SESSION_COOKIE, Identity, is_write_permission

logger = logging.getLogger(__name__)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
SCOPES = ("read", "operate")

# 健康检查要能在没有凭据时访问:它是不带数据的存活探测。
EXEMPT_PATHS = frozenset({"/api/health", "/openapi.json", "/docs", "/redoc"})
# 登录接口本身,以及自带共享密钥的 webhook 入口
EXEMPT_PREFIXES = ("/api/webhook/", "/api/auth/")
TOKEN_HEADER = "x-gwei-token"
AUTH_HEADER = "X-Gwei-Auth"

# 有没有开启鉴权:启动时按"配了令牌或已有用户"决定,首启初始化之后翻转。
_AUTH_STATE = {"required": False}


def set_auth_required(flag: bool) -> None:
    _AUTH_STATE["required"] = bool(flag)


def auth_required() -> bool:
    return _AUTH_STATE["required"]


@dataclass(frozen=True)
class Actor:
    """一次请求的身份。token_id 只用于日志,不回显。"""

    token_id: str
    name: str
    tenant: str = ""  # "" = 不限租户
    scope: str = "read"
    permissions: frozenset[str] = field(default_factory=frozenset)
    user_id: str = ""

    @property
    def can_write(self) -> bool:
        """会话身份看权限;令牌身份看 scope(read/operate)。"""
        if self.permissions:
            return any(is_write_permission(p) for p in self.permissions)
        return self.scope == "operate"

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def __repr__(self) -> str:  # 别把令牌打进日志
        return f"Actor(name={self.name!r}, tenant={self.tenant!r}, scope={self.scope!r})"


class TokenConfigError(ValueError):
    """令牌配置写错。启动即报错——写错的令牌不能静默降级成"不鉴权"。"""


def load_tokens(raw: str) -> dict[str, Actor]:
    """解析令牌列表。任何一行写错都拒绝启动。"""
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


def _actor_from_identity(identity: Identity) -> Actor:
    return Actor(
        token_id="session",
        name=identity.name,
        tenant=identity.tenant,
        scope="operate" if identity.can_write else "read",
        permissions=identity.permissions,
        user_id=identity.user_id,
    )


def make_middleware(tokens: dict[str, Actor]) -> Callable[..., Any]:
    """挂到 app 上的鉴权中间件。"""

    async def middleware(request: Request, call_next):
        request.state.actor = None
        request.state.identity = None
        path = request.url.path
        exempt = (
            not path.startswith("/api/")
            or path in EXEMPT_PATHS
            or path.startswith(EXEMPT_PREFIXES)
        )

        # 1) 先认人:有会话 cookie 就用它。豁免路径也要认——/api/auth/me 靠它回答"我是谁"
        token = request.cookies.get(SESSION_COOKIE, "")
        if token:
            try:
                from engine.auth import store as auth_store

                identity = await auth_store.resolve_session(token)
            except Exception:  # noqa: BLE001 - 库暂时读不到不该让整个站点 500
                logger.warning("会话解析失败", exc_info=True)
                identity = None
            if identity is not None:
                request.state.identity = identity
                request.state.actor = _actor_from_identity(identity)

        # 2) 再认机器:令牌
        if request.state.actor is None:
            actor = tokens.get((request.headers.get(TOKEN_HEADER) or "").strip())
            if actor is not None:
                request.state.actor = actor

        # 3) 该拦就拦。配了令牌就算开着鉴权——这是旧行为,不能因为加了会话就放松
        guarded = auth_required() or bool(tokens)
        if not exempt and guarded:
            actor = request.state.actor
            if actor is None:
                return JSONResponse({"detail": "未登录或令牌无效"}, status_code=401)
            if request.method not in SAFE_METHODS and not actor.can_write:
                return JSONResponse(
                    {"detail": f"这个身份只读,不能 {request.method}"}, status_code=403
                )

        response = await call_next(request)
        response.headers[AUTH_HEADER] = "on" if (auth_required() or tokens) else "off"
        return response

    return middleware


def actor_of(request: Request) -> Actor | None:
    return getattr(request.state, "actor", None)


def require(request: Request, permission: str) -> None:
    """按权限拦。没配鉴权时不拦——那种部署是单机自用,拦了反而没法用。"""
    if not auth_required():
        return
    actor = actor_of(request)
    if actor is None:
        raise HTTPException(status_code=401, detail="未登录或令牌无效")
    # 令牌身份没有细粒度权限,只有 read/operate;只读令牌由中间件拦
    if actor.permissions and not actor.has(permission):
        raise HTTPException(status_code=403, detail=f"缺少权限 {permission}")


def tenant_scope(request: Request, requested: str | None) -> str | None:
    """令牌声明的租户优先于查询参数;两者不一致是越权,不是覆盖。"""
    actor = actor_of(request)
    if actor is None or not actor.tenant:
        return requested
    if requested and requested != actor.tenant:
        raise HTTPException(status_code=403, detail="这个令牌看不到该租户的账")
    return actor.tenant


def by_of(request: Request, declared: str) -> str:
    """谁做的这件事。有身份时以身份为准,请求里写的只是没有鉴权时的替代品。"""
    actor = actor_of(request)
    return actor.name if actor else declared


__all__ = [
    "Actor",
    "TokenConfigError",
    "load_tokens",
    "make_middleware",
    "actor_of",
    "require",
    "set_auth_required",
    "auth_required",
    "tenant_scope",
    "by_of",
    "TOKEN_HEADER",
    "AUTH_HEADER",
]
