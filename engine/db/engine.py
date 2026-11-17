# engine/db/engine.py
"""连接池与"这条连接属于哪个工作区"。

共享部署里隔离落在库上(`engine/db/tenancy.py`):每张租户可见的表都有策略,策略读会话
变量 `gwei.tenant`。**核心自己的连接也必须设它**——不设的话变量是空的,比较恒假,
核心一条数据都读不出来;而"为了读得出来就不设"等于把隔离让给了每一处 SQL 的自觉。

所以缺省是**一个工作区都不属于**,要跨工作区读,调用方必须显式说:

    async with connecting(tenant="acme") as session:        # 一个工作区
        ...
    async with connecting(tenant="*") as session:           # 明确不限(登录、维护脚本)
        ...

`connecting` 把租户写进**这一条事务**,同时把这件事记在 context 上。`tenant_scope()` /
会话 / 审计那条链拿到工作区之后用 `use_tenant()` 把它落到当前上下文,后面所有
`async_session_factory()` 都会自动带上——一处设,处处生效,不用在 59 个 `async with`
上各写一遍。

**为什么是连接事件而不是每条 SQL 前面 SET 一次**:连接从池子里借出来是复用的,
上一个事务的租户会留在连接上。用 `SET LOCAL`(事务本地)在 `begin` 时就写一遍,
事务结束自动复位,下一个借到这条连接的请求不会看见别人的账。
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from typing import AsyncIterator, Final

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from engine.db.tenancy import PERSON_SETTING, TENANT_SETTING
from engine.shared.config import Settings

settings = Settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=10,
    max_overflow=20,
)

# "不限"在上下文里用一个专门的哨兵表示,不是空串。两件事要分开:
#
# - **没定** = 这条连接不知道自己在哪个工作区 → 会话变量写空 → 策略一行都不给。
#   单租户的部署、`create_all` 建出来的裸表、迁移还没跑过的库,都是这种状态,
#   它们本来就没有策略,写空也没人看。
# - **不限** = 这次请求明确跨工作区(认证、维护脚本、按令牌读全量)→ 会话变量写 `*`,
#   策略里写成"`current_setting` 为空**或**等于 `*`",于是全放。
#
# 把"不限"偷偷写成空串是不行的:空串在策略里就是"所有租户之外的那个值",
# 结果是"看不见",而不是"都看见" —— 一个静默的 0 行,比报错难查得多。
NO_TENANT: Final = ""
ANY_TENANT: Final = "*"

_current_tenant: ContextVar[str] = ContextVar("gwei_current_tenant", default=NO_TENANT)
_current_person: ContextVar[str] = ContextVar("gwei_current_person", default=NO_TENANT)


def current_tenant() -> str:
    return _current_tenant.get()


def _bind_scope(connection) -> None:  # noqa: ANN001 - SQLAlchemy 的 Connection
    """把上下文里的租户写进这条事务。空值也写:它就是"什么都看不见"的意思。"""
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        text(f"SELECT set_config('{TENANT_SETTING}', :t, true)"), {"t": current_tenant()}
    )
    connection.execute(
        text(f"SELECT set_config('{PERSON_SETTING}', :p, true)"), {"p": _current_person.get()}
    )


@event.listens_for(engine.sync_engine, "begin")
def _on_begin(connection) -> None:  # noqa: ANN001
    _bind_scope(connection)


def _sync_url(url: str) -> str:
    return url.replace("+asyncpg", "").replace("+psycopg_async", "")


def _migrated(connection) -> bool:
    """这套库跑过迁移没有。没跑过就没有策略、也没有清单表,不必多问一句。"""
    try:
        found = connection.execute(
            text("SELECT to_regclass('public.tenancy_policy_manifest') IS NOT NULL")
        ).scalar()
        return bool(found)
    except Exception:  # noqa: BLE001 - 连不上/没权限都在这里,交给调用方判断
        return False


async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def connecting(tenant: str = NO_TENANT) -> AsyncIterator[AsyncSession]:
    """一条知道自己在哪个工作区里的会话。

    `tenant` 给一个工作区 slug 或 `"*"`。`"*"` 写进会话变量的是空串 ——
    策略那边"空 = 什么都不是",对核心来说就是"这次别按工作区筛",由 SQL 自己决定读哪些行。
    """
    token = _current_tenant.set(_tenant_value(tenant))
    try:
        async with async_session_factory() as session:
            yield session
    finally:
        _current_tenant.reset(token)


def _tenant_value(tenant: str) -> str:
    if tenant in (None, ""):
        return NO_TENANT
    return str(tenant)


@asynccontextmanager
async def connecting_any() -> AsyncIterator[AsyncSession]:
    """明确声明"不限工作区"的会话。认证、维护脚本、跨工作区的对照查询用它。

    名字长一点是故意的:每一次调用都是在说"这里不按工作区筛",读代码的人应该看见它。
    """
    token = _current_tenant.set(NO_TENANT)
    try:
        async with async_session_factory() as session:
            yield session
    finally:
        _current_tenant.reset(token)


def use_tenant(tenant: str | None) -> Token:
    """把这次请求的工作区落到上下文。返回 token 供调用方复位。

    中间件与鉴权那条链用它:认完人、定下这次落在哪个工作区之后调一次,
    后面的所有会话就都带着它。`None` 与 `"*"` 一样 = 不限。
    """
    return _current_tenant.set(_tenant_value(tenant))


def reset_tenant(token: Token) -> None:
    _current_tenant.reset(token)


def use_person(person_id: str | None) -> Token:
    """把"这次请求背后的人"落到上下文。策略里 `persons` 那一行靠它认自己。"""
    return _current_person.set(str(person_id) if person_id else NO_TENANT)


def reset_person(token: Token) -> None:
    _current_person.reset(token)


async def missing_isolation() -> list[str]:
    """启动时问一句:清单里的表在库里都开了策略吗。

    只在"这套库跑过迁移"的前提下问。`create_all` 建出来的裸表(单测、联调)没有
    策略也没有清单表,那不是这台机器该负责的事 —— 靠迁移建库才是。
    """
    from engine.db.tenancy import isolated_tables

    names = list(isolated_tables())
    async with engine.connect() as conn:
        has_manifest = await conn.run_sync(_migrated)
        if not has_manifest:
            return []
        found = set(
            (
                await conn.execute(
                    text("SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation'")
                )
            ).scalars()
        )
    return [name for name in names if name not in found]


async def enforce_isolation() -> None:
    """生产形态下缺策略就不启动。

    判断标准是一个部署有没有可能装多家客户:saas 档有这个可能,selfhost 档
    (单租户 N=1)没有。两种档位跑的是同一份代码,所以这条检查也在同一处。
    """
    missing = await missing_isolation()
    if not missing:
        return
    message = (
        "这些表没有租户隔离策略: "
        + "、".join(missing)
        + "。跑 `alembic upgrade head`,或者把它们加进 engine/db/tenancy.py "
        "的 isolated_tables() 并补一条迁移"
    )
    if settings.deployment_mode == "saas" or os.environ.get("GWEI_REQUIRE_ISOLATION") == "1":
        raise RuntimeError(message)
    import logging

    logging.getLogger(__name__).warning("%s(当前档位:%s)", message, settings.deployment_mode)


async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


__all__ = [
    "async_session_factory",
    "connecting",
    "connecting_any",
    "current_tenant",
    "engine",
    "enforce_isolation",
    "get_db",
    "missing_isolation",
    "reset_person",
    "reset_tenant",
    "use_person",
    "use_tenant",
]
