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
import re
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
# 接邀请的一条口:被邀请的人那时还没有账号,不该为了接一条邀请先有权限。
# 只有 GET/POST 这一个 token 路径豁免,列表与发邀请仍然要登录与 users.manage。
INVITE_PATH = re.compile(r"^/api/invitations/[^/]+$")
TOKEN_HEADER = "x-gwei-token"
# 工作区就这么带:`/api/workspaces/{slug}/...`。写在前缀里的那一段,而不是一个
# 查询参数或请求头 —— 资源要有 URL,链接、分享、日志、审计都自带"这是哪一道账"。
WORKSPACE_PREFIX = "/api/workspaces/"
WORKSPACE_SEGMENT = re.compile(r"^/api/workspaces/([^/]+)/")
# 工作区那一段就剩一个 slug(`/api/workspaces/acme`)时也要认:它是"这个工作区的
# 门牌",写 `/api/workspaces/acme/issues` 才是里面的东西。
EXACT_WORKSPACE = re.compile(r"^/api/workspaces/([^/]+)$")
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
    # 这个人(跨工作区那份凭据的持有者)。会话挂在它上面,不在成员关系上
    person_id: str = ""
    # 这次请求落在哪个工作区(路径里的那一段)
    workspace: str = ""
    # 只在这个范围内生效的权限:{"changes.approve": frozenset({"acme"})}。
    # 同一个权限在工作区级与范围级都可能有,所以两者分开记;范围是 projects 里的
    # slug,项目与仓库共用一个名字空间,判定链见 require() 与
    # docs/explanation/identity-and-authorization.md。
    scoped_permissions: dict[str, frozenset[str]] = field(default_factory=dict)

    @property
    def can_write(self) -> bool:
        """有权限集就看权限;静态令牌只有 scope(read/operate)。"""
        if self.permissions:
            return any(is_write_permission(p) for p in self.permissions)
        return self.scope == "operate"

    def has(self, permission: str) -> bool:
        """工作区级的权限。带范围的权限**不**算在这里:它得指名道姓说范围。"""
        return permission in self.permissions

    def has_scope(self, permission: str) -> bool:
        """这个权限是不是收了范围。接口据此多接一个 `repo`,在判定处再说一次话。"""
        return permission in self.scoped_permissions

    def allows(
        self,
        permission: str,
        repo: str | None = None,
        project: str | None = None,
    ) -> bool:
        """这次判定算不算数。`repo` 与 `project` 都空 = 整个工作区。判据只此一处。

        授在项目上的授权,对项目下每一个仓库都算数 —— 包括登录之后才加进
        来的那个。所以这一档不能在建身份时展开成仓库,只能在判定时问。
        """
        if permission in self.permissions:
            return True
        if not permission:
            return False
        granted = self.scoped_permissions.get(permission, frozenset())
        if repo and repo in granted:
            return True
        return bool(project and project in granted)

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
        person_id=identity.person_id,
        workspace=identity.tenant,
        scoped_permissions=identity.scoped_permissions,
    )


def make_middleware(tokens: dict[str, Actor]) -> Callable[..., Any]:
    """挂到 app 上的鉴权中间件。

    它做两件事:认身份(会话 → 人 → 这次请求落在哪个工作区),和把
    `/api/workspaces/{slug}/…` 折成路由认得的那条路径。折路径放在这里是因为
    它是**所有**接口共用的一步:每个路由自己解析一遍工作区段,迟早有一处忘了解析,
    那一处就会静默地落到默认工作区。
    """

    async def middleware(request: Request, call_next):
        # 中间件栈里 `state` 落在一份独立的 dict 上:`request.state` 的写入到不了
        # 下游,所以身份与工作区要**同时**写进 scope —— 那里才是所有请求共用的一份。
        request.scope.setdefault("state", {})
        request.scope["actor"] = None
        request.scope["identity"] = None
        request.scope["workspace"] = None
        path = request.url.path
        workspace = workspace_of(request)
        # MCP 是一个端点承载读与写:"这次算不算写"由具体工具决定,
        # 不能因为它是 POST 就把只读身份挡在门外。
        is_mcp = path == "/mcp" or path.startswith("/mcp/")
        exempt = (
            not (path.startswith("/api/") or is_mcp)
            or path in EXEMPT_PATHS
            or path.startswith(EXEMPT_PREFIXES)
            or bool(INVITE_PATH.match(path))
        )

        # 1) 先认人:有会话 cookie 就用它。豁免路径也要认——/api/auth/me 靠它回答"我是谁"
        token = request.cookies.get(SESSION_COOKIE, "")
        if token:
            try:
                from engine.auth import store as auth_store

                identity = await auth_store.resolve_session(token, workspace)
            except Exception:  # noqa: BLE001 - 库暂时读不到不该让整个站点 500
                logger.warning("会话解析失败", exc_info=True)
                identity = None
            if identity is not None:
                if workspace and identity.tenant != workspace:
                    # 不属于这个工作区:403 并说清是哪一个,不替他落回他有权限的那一个。
                    # 静默换位会让"我点了 Acme 却看到 Beta 的账"变成常态。
                    return JSONResponse(
                        {"detail": f"你不属于工作区 {workspace}"}, status_code=403
                    )
                request.scope["identity"] = identity
                request.scope["actor"] = _actor_from_identity(identity)

        # 2) 再认机器:库里的密钥优先(可吊销、带权限),静态令牌兜底
        if request.scope.get("actor") is None:
            presented = (request.headers.get(TOKEN_HEADER) or "").strip()
            actor = tokens.get(presented)
            if actor is not None:
                request.scope["actor"] = actor
            elif presented:
                from engine.auth import keys as key_store

                if key_store.looks_like_key(presented):
                    try:
                        key = await key_store.resolve_key(presented)
                    except Exception:  # noqa: BLE001 - 库不可用按"认不出"处理
                        logger.warning("密钥解析失败", exc_info=True)
                        key = None
                    if key is not None:
                        request.scope["actor"] = _actor_from_key(key)
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
            actor = request.scope.get("actor")
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

        if workspace and not exempt:
            # 路径里写了工作区:折成路由认得的那条,再交给下游。
            #
            # 折的是**这一次调用的 scope**(原地改再传下去),不是新造一个 Request:
            # FastAPI 的中间件按原来那份 scope 分发请求,新造的那个只影响我们自己
            # 看得到的 `url`,下游照旧按原路径找路由,结果是 `{"detail":"Not Found"}`。
            request.scope["_workspace_path"] = path
            request.scope["path"] = rest_of_exact(path)
            raw = request.scope.get("raw_path") or path.encode("utf-8")
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            raw_path, _, search = raw.partition("?")
            request.scope["raw_path"] = (
                rest_of_exact(raw_path) + ("?" + search if search else "")
            ).encode("utf-8")
            response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers[AUTH_HEADER] = "on" if (auth_required() or tokens) else "off"
        return response

    return middleware


def workspace_of(request: Request) -> str:
    """这次请求落在哪个工作区。空串 = 没写工作区段。

    写了就是 URL 里那一段,别处(查询串、cookie、请求头)再写一次都不算数:一个
    东西两个真相源,迟早一边说 Acme 一边说 Beta。
    """
    value = _in_scope(request, "workspace")
    if value is not None:
        return str(value)
    scope = getattr(request, "scope", None) or {}
    url = getattr(request, "url", None)
    # 折过路径之后 `url.path` 已经不是用户写的那条了;原始那段留在 `_workspace_path`
    path = str(scope.get("_workspace_path") or getattr(url, "path", "") or "")
    match = WORKSPACE_SEGMENT.match(path) or EXACT_WORKSPACE.match(path)
    slug = match.group(1) if match else ""
    scope = getattr(request, "scope", None)
    if scope is not None:
        scope["workspace"] = slug
    return slug


def rest_of(path: str) -> str:
    """`/api/workspaces/acme/issues` → `/api/issues`。路由按这个形状注册。"""
    return WORKSPACE_SEGMENT.sub("/api/", path, count=1)


def rest_of_exact(path: str) -> str:
    """`/api/workspaces/acme` → `/api/workspaces`。

    同一段字符在两个位置上是两件事:工作区门牌(`/api/me` 那种)与工作区列表
    (`GET /api/workspaces`)。折的时候按它原来是谁折。
    """
    if EXACT_WORKSPACE.match(path):
        return "/api/workspaces"
    return rest_of(path)


def require_workspace(request: Request) -> str:
    """路径里写了工作区就返回它;没写返回空串(沿用令牌声明的那一个)。"""
    return workspace_of(request)


def identity_of(request: Request) -> Identity | None:
    """这次请求背后的人(与他在哪个工作区)。与 `actor_of` 同一个来源。"""
    return _in_scope(request, "identity")


def _in_scope(request: Request, key: str):
    """从 scope 里取一件东西。没有 scope 的对象(测试替身)走 `request.state`。

    中间件栈里 `request.state` 是一份独立的 dict,写在里面的东西到不了下游,
    所以身份与工作区必须落在 scope 上 —— 那是整条请求共用的一份。
    """
    scope = getattr(request, "scope", None)
    if scope is not None and key in scope:
        return scope[key]
    return getattr(getattr(request, "state", None), key, None)


def actor_of(request: Request) -> Actor | None:
    """这次请求的身份。"""
    return _in_scope(request, "actor")


def require(
    request: Request,
    permission: str,
    repo: str | None = None,
    project: str | None = None,
) -> None:
    """按权限拦。没配鉴权时不拦——那种部署是单机自用,拦了反而没法用。

    `repo` 是这道判定的范围,`project` 是仓库所属项目的 slug:两者都空 = 整个
    工作区;给一个仓库 slug = 只在那一个仓库上算数。带范围的授权(`changes.approve`
    只授给 `acme/api`,或只授给项目 `acme`)在工作区级**不算**有权限:同一个
    权限在工作区级与带范围都可能有,混在一起,"只管这一个仓库"就没有答案了。

    判定链是 repo → project → 工作区:项目授权对项目下每一个仓库算数,包括
    登录之后才加进项目里的那个。所以项目这一档只能在判定时问,不能在建身份时
    展开成一份仓库清单。
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
    if repo or project:
        if actor.allows(permission, repo, project):
            return
    if actor.has_scope(permission) and not repo and not project:
        raise HTTPException(
            status_code=403,
            detail=f"这个身份的 {permission} 只对具体范围生效,这个操作覆盖整个工作区",
        )
    raise HTTPException(status_code=403, detail=f"缺少权限 {permission}")


def workspace_access(request: Request) -> str | None:
    """这道账属于哪个工作区 —— 带鉴权的那一版。所有接口都该用它。

    `tenant_scope` 只回答"能不能",这里回答"能不能,以及是哪一个":

    | 情形 | 结果 |
    | --- | --- |
    | 路径里写了工作区,且他是这个工作区的成员 | 用这个 |
    | 路径里写了,但他不是成员 | 403,说清是哪一个 |
    | 路径里没写,令牌声明了租户 | 用令牌那一个 |
    | 路径里没写,令牌的租户是 `*`(跨租户的维护令牌) | `None` = 不限,看得见全部 |
    | 路径里没写,也没有人登录(没配鉴权的部署) | `None` = 不限 |

    机器那侧一字不变:令牌本来就写死一个租户,路径里写了另一个就是 403。

    **空串与 None 不是一回事**:`None` 是"不限",空串是"没有工作区(一个都看不到)"。
    把不限写成空串,账本会按空租户去筛,一行都读不出来 —— 那是把权限放大成
    看不见,同样是个 bug。
    """
    actor = actor_of(request)
    declared = workspace_of(request)
    if actor is None:
        return declared or None
    if declared:
        # 请求的工作区先把 URL 折过一遍(见 make_middleware),这里要的是用户**写的**
        # 那一段 —— 否则"写了别人的工作区"永远不会被判成 403。
        scope = getattr(request, "scope", None) or {}
        requested = str(scope.get("_workspace_path") or "")
        written = (
            WORKSPACE_SEGMENT.match(requested) or EXACT_WORKSPACE.match(requested)
        )
        wanted = written.group(1) if written else declared
        if actor.tenant and wanted != actor.tenant:
            raise HTTPException(status_code=403, detail=f"你不属于工作区 {wanted}")
        return wanted
    return actor.tenant or None


def tenant_scope(request: Request, requested: str | None) -> str | None:
    """这道账属于哪个工作区。判据按顺序,只认前面那条:

    1. URL 里的工作区段 —— 唯一被认的"我说要哪个"
    2. 令牌 / 会话自己声明的那一个
    没有第三条。查询串里的 `tenant` 现在会 400 并指向路径写法 —— 留着它当影子,
    迟早一边说 Acme 一边说 Beta。

    两者不一致是越权,不是覆盖。
    """
    actor = actor_of(request)
    declared = workspace_of(request)
    if actor is not None and actor.tenant:
        if declared and declared != actor.tenant:
            raise HTTPException(status_code=403, detail=f"你不属于工作区 {declared}")
        _reject_query_tenant(requested)
        return actor.tenant
    _reject_query_tenant(requested)
    return declared or None


def _reject_query_tenant(requested: str | None) -> None:
    """查询串传工作区已经不作数了。报错比静默忽略好:静默忽略会让调用方以为生效了。"""
    if requested:
        raise HTTPException(
            status_code=400,
            detail="工作区写在路径里:/api/workspaces/{工作区}/…;查询串的 tenant 不再生效",
        )


def by_of(request: Request, declared: str) -> str:
    """谁做的这件事。有身份时以身份为准,请求里写的只是没有鉴权时的替代品。"""
    actor = actor_of(request)
    return actor.name if actor else declared


__all__ = [
    "Actor",
    "workspace_access",
    "identity_of",
    "TokenConfigError",
    "load_tokens",
    "make_middleware",
    "actor_of",
    "require",
    "set_auth_required",
    "auth_required",
    "tenant_scope",
    "by_of",
    "workspace_of",
    "rest_of",
    "TOKEN_HEADER",
    "AUTH_HEADER",
    "WORKSPACE_PREFIX",
]
