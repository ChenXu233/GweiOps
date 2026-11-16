# engine/api/auth.py
"""谁在调用 —— 会话 cookie 给人,令牌与密钥给机器。

在这之前,by 与 tenant 全靠调用方声明。那不是鉴权,是留言:任何人都能说
自己是别人、要看别人的账。

现在有三套凭据,井水不犯河水:

- **人**:POST /api/auth/login 换成会话 cookie(HttpOnly),权限由角色算出来
- **机器**:X-Gwei-Token, `token:tenant:actor:scope`,给 harness 与 alertmanager 用
- **外界 agent**:X-Gwei-Token 里的 `gwei_` 前缀密钥,库里的对象,带自己的权限集
  与工具白名单,单独可吊销。它的工具清单按权限收窄,见 `engine/auth/keys.py`

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

# 只读身份可 POST 的例外:开会话本身不改世界,改不改由工具判——改世界的调用
# 要界面上批准,只读身份也看不到那些工具。与放开读口是同一个理由,不是新入口。
READ_ONLY_POST_PREFIXES = ("/api/console/session",)
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
    # 这把凭据只允许够哪些工具。空 = 不额外收窄(按权限算)。
    tools: frozenset[str] = field(default_factory=frozenset)
    # 这把凭据只允许在哪些资源(下游目标)上动手。空 = 不限。
    bindings: frozenset[str] = field(default_factory=frozenset)
    # 库里的密钥会带 id;静态令牌与会话为空
    key_id: str = ""
    # 这是一个只带 read/operate 的静态令牌。默认不是:没有细粒度权限时按 scope 放行
    # 是个陷阱 —— 权限为空的会话会因此看到全部只读工具。
    static: bool = False
    # 只在这个范围内生效的权限:{"changes.approve": frozenset({"github-acme-api"})}。
    # 同一个权限在工作区级与仓库级都可能有,所以两者分开记 —— 见 engine/auth/scope.py
    scoped_permissions: dict[str, frozenset[str]] = field(default_factory=dict)

    @property
    def can_write(self) -> bool:
        """有权限集就看权限;静态令牌只有 scope(read/operate)。"""
        if self.permissions:
            return any(is_write_permission(p) for p in self.permissions)
        return self.scope == "operate"

    def has(self, permission: str) -> bool:
        """工作区级的权限。带范围的权限**不**算在这里:它得指名道姓地说要哪个仓库。"""
        return permission in self.permissions

    def has_scope(self, permission: str) -> bool:
        """这个权限是不是收了范围。接口据此多接一个 `repo`,在判定处再说一次话。"""
        return permission in self.scoped_permissions

    @property
    def scoped(self) -> bool:
        """权限集说了算吗?静态令牌不是,它只有 read/operate。"""
        return not self.static

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
            static=True,
        )
    return out


def _actor_from_key(key: Any) -> Actor:
    """库里的密钥 → 身份。权限是它的全部,没有"默认全放"。"""
    return Actor(
        token_id="key",
        name=key.name or key.hint or "密钥",
        tenant=key.tenant,
        scope="operate" if any(is_write_permission(p) for p in key.permissions) else "read",
        permissions=key.permissions,
        tools=key.tools,
        bindings=key.bindings,
        key_id=key.id,
    )


def _actor_from_identity(identity: Identity) -> Actor:
    return Actor(
        token_id="session",
        name=identity.name,
        tenant=identity.tenant,
        scope="operate" if identity.can_write else "read",
        permissions=identity.permissions,
        user_id=identity.user_id,
        scoped_permissions=identity.scoped_permissions,
    )


def make_middleware(tokens: dict[str, Actor]) -> Callable[..., Any]:
    """挂到 app 上的鉴权中间件。"""

    async def middleware(request: Request, call_next):
        request.state.actor = None
        request.state.identity = None
        path = request.url.path
        # MCP 是一个端点承载读与写:"这次算不算写"由具体工具决定,
        # 不能因为它是 POST 就把只读身份挡在门外。
        is_mcp = path == "/mcp" or path.startswith("/mcp/")
        exempt = (
            not (path.startswith("/api/") or is_mcp)
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

        # 2) 再认机器:库里的密钥优先(可吊销、带权限),静态令牌兜底
        if request.state.actor is None:
            presented = (request.headers.get(TOKEN_HEADER) or "").strip()
            actor = tokens.get(presented)
            if actor is not None:
                request.state.actor = actor
            elif presented:
                from engine.auth import keys as key_store

                if key_store.looks_like_key(presented):
                    try:
                        key = await key_store.resolve_key(presented)
                    except Exception:  # noqa: BLE001 - 库不可用按"认不出"处理
                        logger.warning("密钥解析失败", exc_info=True)
                        key = None
                    if key is not None:
                        request.state.actor = _actor_from_key(key)
                    elif not exempt:
                        # 拿一把看起来像密钥的东西来敲门,却查不到:这不是匿名请求,
                        # 是没通过的身份认证。它不能落到"没配凭据就不鉴权"那一侧——
                        # 否则吊销只对配了令牌的部署有效,别的部署里被吊销的密钥
                        # 会降级成"自报租户的匿名调用"。
                        return JSONResponse(
                            {"detail": "密钥无效或已吊销"}, status_code=401
                        )

        # 3) 该拦就拦。配了令牌就算开着鉴权——这是旧行为,不能因为加了会话就放松
        guarded = auth_required() or bool(tokens)
        if not exempt and guarded:
            actor = request.state.actor
            if actor is None:
                return JSONResponse({"detail": "未登录或令牌无效"}, status_code=401)
            starts_a_conversation = path.startswith(READ_ONLY_POST_PREFIXES)
            if (
                not is_mcp
                and not starts_a_conversation
                and request.method not in SAFE_METHODS
                and not actor.can_write
            ):
                return JSONResponse(
                    {"detail": f"这个身份只读,不能 {request.method}"}, status_code=403
                )

        response = await call_next(request)
        response.headers[AUTH_HEADER] = "on" if (auth_required() or tokens) else "off"
        return response

    return middleware


def actor_of(request: Request) -> Actor | None:
    return getattr(request.state, "actor", None)


def require(request: Request, permission: str, repo: str | None = None) -> None:
    """按权限拦。没配鉴权时不拦——那种部署是单机自用,拦了反而没法用。

    `repo` 是这道判定的范围:给空 = 整个工作区;给一个仓库 slug = 只在那一个仓库上
    算数。带范围的授权(`changes.approve` 只授给 `acme/api`)在工作区级**不算**
    有权限:同一个权限在工作区级与仓库级都可能有,混在一起,"只管这一个仓库"
    就没有答案了。
    """
    if not auth_required():
        return
    actor = actor_of(request)
    if actor is None:
        raise HTTPException(status_code=401, detail="未登录或令牌无效")
    # 静态令牌没有细粒度权限,只有 read/operate,由中间件拦;其余的按权限集判
    from engine.auth.keys import is_scoped

    if not is_scoped(actor):
        return
    if actor.has(permission):
        return
    if repo and repo in actor.scoped_permissions.get(permission, frozenset()):
        return
    if actor.has_scope(permission) and not repo:
        raise HTTPException(
            status_code=403,
            detail=f"这个身份的 {permission} 只对具体仓库生效,这个操作覆盖整个工作区",
        )
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
