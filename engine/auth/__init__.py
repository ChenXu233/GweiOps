# engine/auth/__init__.py
"""身份与权限 —— 谁在调用、他能做什么、他做过什么。

之前只有机器令牌:一个字符串声明自己是哪个租户、能不能写。那能挡住陌生人,
但挡不住"同一个租户里的两个人",也回答不了"这个变更最后是谁点的头"。

这里把人变成一等对象:

- **权限是原子字符串**(见 PERMISSIONS),贴着现有接口切,不新造概念
- **角色是数据**:租户自己建、自己勾权限;owner/operator/viewer 只是初始化时
  塞进去的三个预设,改得、删得
- **子用户**只能拿到父用户已有的权限(交集),这条在代码里强制,不靠界面提示

密码用标准库的 scrypt:内存硬,不加依赖。会话令牌只存哈希,能在后台踢人。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# 权限目录:一个权限对应一类操作,粒度和接口对齐
# ---------------------------------------------------------------------------

PERMISSIONS: dict[str, str] = {
    "changes.read": "看变更账本与事故",
    "changes.execute": "通过出口改世界(每次调用落成一个变更单元)",
    "changes.approve": "放行被阻断的变更",
    "changes.rollback": "撤销已执行的变更",
    "settings.read": "看配置(密钥只显示是否已设置)",
    "settings.write": "改配置与密钥",
    "users.read": "看用户与角色",
    "users.manage": "增删用户、分配角色",
    "roles.manage": "增删角色、改角色权限",
    "audit.read": "看审计日志",
    "plugins.read": "看插件与能力",
    "plugins.write": "启停插件、重扫插件目录",
    "keys.read": "看密钥清单(明文永不回显)",
    "keys.manage": "签发与吊销密钥",
}

ALL_PERMISSIONS = frozenset(PERMISSIONS)

# 初始化时给租户塞的三个预设。is_system=True 的删不掉,但权限可以改。
DEFAULT_ROLES: tuple[dict, ...] = (
    {
        "key": "owner",
        "name": "所有者",
        "description": "租户的全部权限,包括管人和管角色",
        "permissions": sorted(ALL_PERMISSIONS),
        "is_system": True,
    },
    {
        "key": "operator",
        "name": "运维",
        "description": "看账本、放行与撤销变更、读配置、管 MCP 密钥",
        "permissions": sorted(
            {
                "changes.read",
                "changes.execute",
                "changes.approve",
                "changes.rollback",
                "settings.read",
                "audit.read",
                "plugins.read",
                "keys.read",
                "keys.manage",
            }
        ),
        "is_system": True,
    },
    {
        "key": "viewer",
        "name": "只读",
        "description": "只看,不改任何东西",
        "permissions": sorted({"changes.read", "settings.read", "plugins.read"}),
        "is_system": True,
    },
)

READ_PERMISSIONS = frozenset(
    {"changes.read", "settings.read", "users.read", "audit.read", "plugins.read", "keys.read"}
)

# 可以只授给某几个仓库的权限。**只有会落到具体仓库上的动作**进这张表:
# 放行、撤销、执行都作用在一个仓库上;管人与管密钥是工作区级的事,收窄到仓库
# 没有意义 —— 一个仓库没有自己的用户表。
#
# 不在这张表里的权限没法收窄:角色里给 `changes.read` 收窄到 acme/api,那个人
# 会**看不到任何**东西(包括 acme/api 的账),而不是看到一部分。这是保守那一侧:
# 收窄没生效时不该多给,只该少给。
SCOPED_PERMISSIONS = frozenset({"changes.read", "changes.execute", "changes.approve", "changes.rollback"})

WRITE_PREFIXES = ("changes.approve", "changes.rollback", "settings.write")

SESSION_COOKIE = "gwei_session"
SESSION_DAYS = 14


def is_write_permission(permission: str) -> bool:
    """这个权限会不会改世界。中间件用它决定写请求要不要拦。

    "读"是白名单:新增一个只读权限时把它加进 READ_PERMISSIONS,漏加的后果是
    这个权限被当成可写(保守那一侧),而不是悄悄放行。
    """
    return permission not in READ_PERMISSIONS


# ---------------------------------------------------------------------------
# 密码:scrypt
# ---------------------------------------------------------------------------

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_LEN = 32
_SCRYPT_MAXMEM = 64 * 1024 * 1024


def hash_password(password: str) -> str:
    """scrypt$n$r$p$salt$hash,全部 base64;参数随密码一起存,以后调参不用迁移。"""
    if not password or len(password) < 8:
        raise ValueError("密码至少 8 位")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_LEN,
        maxmem=_SCRYPT_MAXMEM,
    )
    return "scrypt$%d$%d$%d$%s$%s" % (
        _SCRYPT_N,
        _SCRYPT_R,
        _SCRYPT_P,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    """校验密码。格式不认识就当场失败,不悄悄放行。"""
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$")
    except (AttributeError, ValueError):
        return False
    if algo != "scrypt":
        return False
    try:
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=_SCRYPT_MAXMEM,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


# ---------------------------------------------------------------------------
# 会话令牌
# ---------------------------------------------------------------------------


def new_session_token() -> tuple[str, str]:
    """返回 (明文, 哈希)。明文只进 cookie,库里只留哈希。"""
    token = secrets.token_urlsafe(32)
    return token, hash_session_token(token)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiry(days: int = SESSION_DAYS) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


# ---------------------------------------------------------------------------
# 有效权限
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Identity:
    """一次请求背后的人。token_id 只用于日志,不回显。"""

    user_id: str
    name: str
    tenant: str
    # 工作区级的权限:没有范围限制,处处算数
    permissions: frozenset[str]
    parent_id: str = ""
    # 只对某几个仓库生效的权限:{权限: {仓库 slug…}}
    scoped_permissions: dict[str, frozenset[str]] = field(default_factory=dict)

    @property
    def can_write(self) -> bool:
        """会不会改世界。只授给某几个仓库的写权限也算 —— 界面上他要看得见那些按钮。"""
        return any(is_write_permission(p) for p in self.permissions) or any(
            is_write_permission(p) for p in self.scoped_permissions
        )

    def has(self, permission: str) -> bool:
        """工作区级的权限。带范围的不算:它得指名道姓地说要哪个仓库。"""
        return permission in self.permissions

    def has_scope(self, permission: str) -> bool:
        return permission in self.scoped_permissions

    def allows(self, permission: str, scope: str | None = None) -> bool:
        """这次判定算不算数。`scope` 空 = 整个工作区。判据只此一处。"""
        if permission in self.permissions:
            return True
        if not scope or not permission:
            return False
        return scope in self.scoped_permissions.get(permission, frozenset())


def effective_permissions(
    own: set[str] | list[str] | None,
    roles: list[list[str]],
    parent: set[str] | None = None,
) -> frozenset[str]:
    """角色并集 + 个人追加;有父用户时再与父的交集。

    parent=None 表示没有父(顶级用户);空集合表示父被停了或没有权限——
    那种情况下子用户也该是空,不能因为"没传"就放开。
    """
    granted: set[str] = set(own or [])
    for role_permissions in roles:
        granted |= set(role_permissions)
    granted &= set(ALL_PERMISSIONS)
    if parent is not None:
        granted &= set(parent)
    return frozenset(granted)


def split_scoped(
    entries: list[str] | set[str] | None,
) -> tuple[set[str], dict[str, set[str]]]:
    """把 "changes.approve" 与 "changes.approve@github-acme-api" 拆成两份。

    前者是工作区级的授权,后者只对那一个仓库生效(仓库用 slug 指名,见
    `engine/workflows/pipeline.py` 的 `repo_slug`)。同一个权限两边都可能有:
    工作区级那份管别的仓库,带范围那份只管这几个。
    """
    whole: set[str] = set()
    scoped: dict[str, set[str]] = {}
    for entry in entries or ():
        text = str(entry or "").strip()
        if not text:
            continue
        permission, sep, scope = text.partition("@")
        if not sep:
            whole.add(permission)
            continue
        scope = scope.strip()
        if not scope or permission not in SCOPED_PERMISSIONS:
            # 收窄了一个不能收窄的权限(或没写收窄到哪):丢掉,不猜。
            # 按不收窄处理会多给,按收窄处理会少给 —— 少给那一侧才是安全的那侧。
            continue
        scoped.setdefault(permission, set()).add(scope)
    return whole, scoped


def effective_permissions(
    own: set[str] | list[str] | None,
    roles: list[list[str]],
    parent: set[str] | None = None,
    parent_scoped: dict[str, set[str]] | None = None,
) -> tuple[frozenset[str], dict[str, frozenset[str]]]:
    """角色并集 + 个人追加;有父用户时再与父的交集。

    返回 (工作区级权限, 带范围的权限)。parent=None 表示没有父(顶级用户);
    空集合表示父被停了或没有权限——那种情况下子用户也该是空,不能因为"没传"
    就放开。

    带范围的权限与父取交集时按仓库逐个算:父有的仓库才留下,父没有的删掉。
    """
    own_whole, own_scoped = split_scoped(own)
    whole: set[str] = set(own_whole)
    scoped: dict[str, set[str]] = {k: set(v) for k, v in own_scoped.items()}
    for role_permissions in roles:
        role_whole, role_scoped = split_scoped(role_permissions)
        whole |= role_whole
        for permission, scopes in role_scoped.items():
            scoped.setdefault(permission, set()).update(scopes)
    whole &= set(ALL_PERMISSIONS)
    for permission in list(scoped):
        if permission not in SCOPED_PERMISSIONS:
            del scoped[permission]
    if parent is not None:
        whole &= set(parent)
        allowed = parent_scoped or {}
        for permission in list(scoped):
            kept = scoped[permission] & set(allowed.get(permission, ()))
            if kept:
                scoped[permission] = kept
            else:
                del scoped[permission]
    return frozenset(whole), {k: frozenset(v) for k, v in scoped.items()}


__all__ = [
    "ALL_PERMISSIONS",
    "DEFAULT_ROLES",
    "Identity",
    "PERMISSIONS",
    "READ_PERMISSIONS",
    "SESSION_COOKIE",
    "SCOPED_PERMISSIONS",
    "SESSION_DAYS",
    "effective_permissions",
    "split_scoped",
    "hash_password",
    "hash_session_token",
    "is_write_permission",
    "new_session_token",
    "session_expiry",
    "verify_password",
]
