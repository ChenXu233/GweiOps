# engine/auth/keys.py
"""密钥 —— 给外界的 agent 的凭据,以及"它能看到哪些工具"。

控制台令牌(`API_TOKENS`)是部署那一刻的凭据:写在环境变量里、改一次要重启、
一个部署就几条。外界的 agent 不是这个形状 —— 一个客户端一把,各自不同的权限,
随时要能单独吊销。所以密钥是库里的对象:有名字、有权限集、有可选的工具白名单,
明文只在签发那一次出现,库里只留 sha256。

**工具按密钥暴露**:`tools/list` 只列这把密钥够得着的那些,`tools/call` 也只放行
那些。能力名到权限的翻译只在这里做一次,别处不再判第二遍。
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol, runtime_checkable

from engine.auth import ALL_PERMISSIONS

logger = logging.getLogger(__name__)

KEY_PREFIX = "gwei_"
STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"
READ_SUFFIX = ".read"

# 一个工具要么命中精确表,要么按后缀落到两把门槛权限之一 —— 新增插件不必回来改这里。
READ_TOOL_PERMISSION = "changes.read"
EFFECT_PERMISSION = "changes.execute"

# 精确表:能力名与权限目录里的名字对不上时写在这里。
CAPABILITY_PERMISSIONS: dict[str, str] = {
    # 账本、事故、话题是同一件事的三个切面:看得到账就看得全
    "changes.read": "changes.read",
    "incidents.read": "changes.read",
    "topic.read": "changes.read",
    "audit.read": "audit.read",
    "plugins.read": "plugins.read",
}


def permission_for_tool(tool: str) -> str:
    """一个工具需要什么权限。判据只此一处。"""
    if tool in CAPABILITY_PERMISSIONS:
        return CAPABILITY_PERMISSIONS[tool]
    if tool in ALL_PERMISSIONS:
        return tool
    if tool.endswith(READ_SUFFIX):
        return READ_TOOL_PERMISSION
    return EFFECT_PERMISSION


def is_scoped(actor: Any) -> bool:
    """这个身份是"权限集说了算"还是"只有一个 scope"?

    分不清的后果很难看:权限为空的会话或密钥会被当成"没有细粒度权限",
    于是按 scope 放行 —— 而它的 scope 恰好是 read,只读工具就漏出去了。
    """
    return bool(getattr(actor, "scoped", True))


def tool_allowed(tool: str, actor: Any) -> bool:
    """这个身份够不够得着这个工具。

    三种身份各有各的说法:
    - 没有身份(部署没配任何凭据):不筛,单机自用的老行为;
    - 有权限集(会话或密钥):按权限筛,再按密钥自己的白名单收窄;
    - 只有 scope 的静态令牌:`operate` 全放,`read` 只放只读工具。
    """
    if actor is None:
        return True
    narrowed = getattr(actor, "tools", frozenset())
    if narrowed and tool not in narrowed:
        return False
    if is_scoped(actor):
        return permission_for_tool(tool) in getattr(actor, "permissions", frozenset())
    # 静态令牌只有 read/operate,没有权限集
    return getattr(actor, "scope", "read") == "operate" or tool.endswith(READ_SUFFIX)


# ---------------------------------------------------------------------------
# 明文、哈希、提示
# ---------------------------------------------------------------------------


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def hint_for(plaintext: str) -> str:
    """认得出来是哪一把,又换不回明文。"""
    return f"{plaintext[:9]}…{plaintext[-4:]}"


def new_plaintext() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def looks_like_key(token: str) -> bool:
    return bool(token) and token.startswith(KEY_PREFIX)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _expired(expires_at: str) -> bool:
    if not expires_at:
        return False
    try:
        when = datetime.fromisoformat(expires_at)
    except ValueError:
        return True  # 读不懂的到期时间当已过期:放宽的那一边不该是默认
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when <= datetime.now(timezone.utc)


def clean_permissions(raw: Iterable[str] | None) -> list[str]:
    """只留看得懂的权限。空白名单就是"什么都没有",不是"全都有"。"""
    return sorted({p for p in (raw or []) if p in ALL_PERMISSIONS})


@dataclass(frozen=True)
class KeyRecord:
    """一把密钥的事实。不带明文,也不带哈希 —— 调用方不需要它。"""

    id: str
    tenant: str
    name: str
    hint: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    tools: frozenset[str] = field(default_factory=frozenset)
    created_at: str = ""
    created_by: str = ""
    last_used_at: str = ""
    expires_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant": self.tenant,
            "name": self.name,
            "hint": self.hint,
            "permissions": sorted(self.permissions),
            "tools": sorted(self.tools),
            "created_at": self.created_at,
            "created_by": self.created_by,
            "last_used_at": self.last_used_at,
            "expires_at": self.expires_at,
        }


class KeyError_(ValueError):
    """密钥操作被规则拒绝。message 直接给人看。"""


# ---------------------------------------------------------------------------
# 两个后端:业务库(默认)与一个 JSON 文件(演示与离线调试)
# ---------------------------------------------------------------------------


@runtime_checkable
class KeyStore(Protocol):
    async def add(self, row: dict[str, Any]) -> None: ...

    async def list(self, tenant: str) -> list[dict[str, Any]]: ...

    async def find(self, key_hash: str) -> dict[str, Any] | None: ...

    async def revoke(self, tenant: str, key_id: str) -> bool: ...

    async def touch(self, key_id: str, at: str) -> None: ...


class JsonlKeyStore:
    """一个 JSON 文件装全部密钥。只配演示与离线调试,和账本的文件后端同一个开关。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return []
        return [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []

    def _write(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )

    async def add(self, row: dict[str, Any]) -> None:
        rows = self._read()
        rows.append(dict(row))
        self._write(rows)

    async def list(self, tenant: str) -> list[dict[str, Any]]:
        rows = [row for row in self._read() if str(row.get("tenant") or "") == (tenant or "")]
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return rows

    async def find(self, key_hash: str) -> dict[str, Any] | None:
        for row in self._read():
            if row.get("key_hash") == key_hash:
                return row
        return None

    async def revoke(self, tenant: str, key_id: str) -> bool:
        rows = self._read()
        hit = False
        for row in rows:
            if row.get("id") == key_id and str(row.get("tenant") or "") == (tenant or ""):
                row["status"] = STATUS_REVOKED
                hit = True
        if hit:
            self._write(rows)
        return hit

    async def touch(self, key_id: str, at: str) -> None:
        rows = self._read()
        for row in rows:
            if row.get("id") == key_id:
                row["last_used_at"] = at
                self._write(rows)
                return


class DbKeyStore:
    """业务库。与其它表同一种做法:启动时 checkfirst 建一次。"""

    def _factory(self):
        from engine.db import async_session_factory

        return async_session_factory

    @staticmethod
    def _row_dict(row: Any) -> dict[str, Any]:
        return {
            "id": row.id,
            "tenant": row.tenant,
            "name": row.name,
            "hint": row.hint,
            "key_hash": row.key_hash,
            "permissions": list(row.permissions or []),
            "tools": list(row.tools or []),
            "status": row.status,
            "created_at": row.created_at or "",
            "created_by": row.created_by or "",
            "last_used_at": row.last_used_at or "",
            "expires_at": row.expires_at or "",
        }

    async def add(self, row: dict[str, Any]) -> None:
        from engine.db.models.api_key import ApiKey

        async with self._factory()() as session:
            session.add(ApiKey(**row))
            await session.commit()

    async def list(self, tenant: str) -> list[dict[str, Any]]:
        from sqlalchemy import select

        from engine.db.models.api_key import ApiKey

        async with self._factory()() as session:
            rows = (
                await session.execute(
                    select(ApiKey)
                    .where(ApiKey.tenant == (tenant or ""))
                    .order_by(ApiKey.created_at.desc())
                )
            ).scalars()
            return [self._row_dict(row) for row in rows]

    async def find(self, key_hash: str) -> dict[str, Any] | None:
        from sqlalchemy import select

        from engine.db.models.api_key import ApiKey

        async with self._factory()() as session:
            row = await session.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
            return self._row_dict(row) if row is not None else None

    async def revoke(self, tenant: str, key_id: str) -> bool:
        from engine.db.models.api_key import ApiKey

        async with self._factory()() as session:
            row = await session.get(ApiKey, key_id)
            if row is None or row.tenant != (tenant or ""):
                return False
            row.status = STATUS_REVOKED
            await session.commit()
            return True

    async def touch(self, key_id: str, at: str) -> None:
        from engine.db.models.api_key import ApiKey

        async with self._factory()() as session:
            row = await session.get(ApiKey, key_id)
            if row is None:
                return
            row.last_used_at = at
            await session.commit()


def create_key_store() -> KeyStore:
    """按账本的同一个开关选实现:file 给演示与离线调试,db 是默认。"""
    from engine.shared.config import config

    if config.settings.change_ledger_backend == "file":
        ledger = Path(config.settings.change_ledger_path)
        return JsonlKeyStore(ledger.with_name("api-keys.json"))
    return DbKeyStore()


async def ensure_schema() -> None:
    """建表(已存在就跳过)。与其它模型同一种做法。"""
    from engine.db import engine as db_engine
    from engine.db.models.api_key import ApiKey

    async with db_engine.begin() as conn:
        await conn.run_sync(lambda c: ApiKey.__table__.create(c, checkfirst=True))


# ---------------------------------------------------------------------------
# 对外的动作
# ---------------------------------------------------------------------------


def _record(row: dict[str, Any]) -> KeyRecord:
    return KeyRecord(
        id=str(row.get("id") or ""),
        tenant=str(row.get("tenant") or ""),
        name=str(row.get("name") or ""),
        hint=str(row.get("hint") or ""),
        permissions=frozenset(row.get("permissions") or []),
        tools=frozenset(row.get("tools") or []),
        created_at=str(row.get("created_at") or ""),
        created_by=str(row.get("created_by") or ""),
        last_used_at=str(row.get("last_used_at") or ""),
        expires_at=str(row.get("expires_at") or ""),
    )


async def create_key(
    *,
    tenant: str,
    name: str,
    permissions: Iterable[str] | None = None,
    tools: Iterable[str] | None = None,
    created_by: str = "",
    expires_at: str = "",
) -> tuple[KeyRecord, str]:
    """签发一把。返回 (记录, 明文) —— 明文只在这里出现一次。"""
    import uuid

    if not (name or "").strip():
        raise KeyError_("密钥得有个名字,不然吊销的时候认不出是哪一把")
    if expires_at:
        try:
            datetime.fromisoformat(expires_at)
        except ValueError:
            raise KeyError_("到期时间要写成 ISO 8601,例如 2026-12-31T00:00:00+00:00") from None

    plaintext = new_plaintext()
    row = {
        "id": str(uuid.uuid4()),
        "tenant": tenant or "",
        "name": name.strip()[:64],
        "hint": hint_for(plaintext),
        "key_hash": hash_key(plaintext),
        "permissions": clean_permissions(permissions),
        "tools": [str(t) for t in (tools or [])],
        "status": STATUS_ACTIVE,
        "created_at": _now(),
        "created_by": created_by[:64],
        "last_used_at": "",
        "expires_at": expires_at,
    }
    await create_key_store().add(row)
    return _record(row), plaintext


async def list_keys(tenant: str) -> list[KeyRecord]:
    return [_record(row) for row in await create_key_store().list(tenant)]


async def revoke_key(tenant: str, key_id: str) -> bool:
    """吊销:记录留着(谁签的、什么时候用过还看得见),状态改掉。"""
    return await create_key_store().revoke(tenant, key_id)


async def resolve_key(plaintext: str) -> KeyRecord | None:
    """明文 → 记录。库里没这把、已吊销、已过期都返回 None。

    读不到库(还没建表)也返回 None:认不出的凭据就是不认,
    不能因为查不动就放行。
    """
    if not looks_like_key(plaintext):
        return None
    store = create_key_store()
    try:
        row = await store.find(hash_key(plaintext))
    except Exception:  # noqa: BLE001 - 库不可用不等于"这把密钥有效"
        logger.warning("密钥查询失败", exc_info=True)
        return None
    if row is None:
        return None
    if row.get("status") != STATUS_ACTIVE or _expired(str(row.get("expires_at") or "")):
        return None
    await _touch(store, row)
    return _record(row)


async def _touch(store: KeyStore, row: dict[str, Any]) -> None:
    """记活跃时间,五分钟一次:每个请求都写库没必要,但"最后用过"要准到分钟。"""
    last = str(row.get("last_used_at") or "")
    now = datetime.now(timezone.utc)
    if last:
        try:
            prev = datetime.fromisoformat(last)
            if prev.tzinfo is None:
                prev = prev.replace(tzinfo=timezone.utc)
            if (now - prev).total_seconds() <= 300:
                return
        except ValueError:
            pass
    try:
        await store.touch(str(row.get("id") or ""), now.isoformat(timespec="seconds"))
    except Exception:  # noqa: BLE001 - 记不上活跃时间不该让请求失败
        logger.debug("密钥活跃时间没记上", exc_info=True)


__all__ = [
    "CAPABILITY_PERMISSIONS",
    "DbKeyStore",
    "EFFECT_PERMISSION",
    "JsonlKeyStore",
    "KEY_PREFIX",
    "KeyError_",
    "KeyRecord",
    "KeyStore",
    "READ_TOOL_PERMISSION",
    "STATUS_ACTIVE",
    "STATUS_REVOKED",
    "clean_permissions",
    "create_key",
    "create_key_store",
    "ensure_schema",
    "hash_key",
    "hint_for",
    "is_scoped",
    "list_keys",
    "looks_like_key",
    "new_plaintext",
    "permission_for_tool",
    "resolve_key",
    "revoke_key",
    "tool_allowed",
]
