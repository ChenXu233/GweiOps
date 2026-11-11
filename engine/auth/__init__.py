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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# 权限目录:一个权限对应一类操作,粒度和接口对齐
# ---------------------------------------------------------------------------

PERMISSIONS: dict[str, str] = {
    "changes.read": "看变更账本与事故",
    "changes.approve": "放行被阻断的变更",
    "changes.rollback": "撤销已执行的变更",
    "settings.read": "看配置(密钥只显示是否已设置)",
    "settings.write": "改配置与密钥",
    "users.read": "看用户与角色",
    "users.manage": "增删用户、分配角色",
    "roles.manage": "增删角色、改角色权限",
    "audit.read": "看审计日志",
    "plugins.read": "看插件与能力",
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
        "description": "看账本、放行与撤销变更、读配置",
        "permissions": sorted(
            {
                "changes.read",
                "changes.approve",
                "changes.rollback",
                "settings.read",
                "audit.read",
                "plugins.read",
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

WRITE_PREFIXES = ("changes.approve", "changes.rollback", "settings.write")

SESSION_COOKIE = "gwei_session"
SESSION_DAYS = 14


def is_write_permission(permission: str) -> bool:
    """这个权限会不会改世界。中间件用它决定写请求要不要拦。"""
    return permission not in ("changes.read", "settings.read", "users.read", "audit.read", "plugins.read")


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
    permissions: frozenset[str]
    parent_id: str = ""

    @property
    def can_write(self) -> bool:
        return any(is_write_permission(p) for p in self.permissions)

    def has(self, permission: str) -> bool:
        return permission in self.permissions


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


__all__ = [
    "ALL_PERMISSIONS",
    "DEFAULT_ROLES",
    "Identity",
    "PERMISSIONS",
    "SESSION_COOKIE",
    "SESSION_DAYS",
    "effective_permissions",
    "hash_password",
    "hash_session_token",
    "is_write_permission",
    "new_session_token",
    "session_expiry",
    "verify_password",
]
