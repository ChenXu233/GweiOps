# engine/plugin_manager/data.py
"""插件读库的通道 —— 分级、按租户收口、结构强制。

一个插件能不能读库、读到什么,现在有两层,缺一不可:

1. **声明**(清单 `data.scopes`):`read:own` / `write:own` / `host` 三档。
   写错的名字在清单解析时被拒;外部插件声明 `data.scopes` 直接被拒,声明 `host`
   而插件不是本仓库内置的也被拒。拒的是声明,插件因此装不上——这是第一层强制。
2. **连接**(本模块的 `plugin_session`):拿到的是一条每条事务都 `SET LOCAL`
   租户的会话。库侧的 RLS 策略按 `gwei.tenant` 收口,插件忘了带 `where` 的后果
   是读到空集,不是读到别人的账。

**不发连接串**。给插件一个 `DATABASE_URL` 就等于这次分级白做——它连 `users`、
`api_keys` 都读得到。插件拿到的是核心给的会话对象,不是一个可以带去别处的凭据。

进程外插件走不到这里:它的代码不在核心进程里,拿不到这个模块。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 库侧策略读的那个会话变量。RLS 表达式是
#   current_setting('gwei.tenant', true) = tenant
# 第二个参数 true = 没设过就返回 NULL,不抛错。NULL 与 tenant 比较永远为假,
# 于是"忘了设"的默认结果是**什么都看不见**,而不是什么都看得见。
TENANT_SETTING = "gwei.tenant"

READ_SCOPES = frozenset({"read:own"})
WRITE_SCOPES = frozenset({"write:own"})


class DataScopeError(PermissionError):
    """插件要的数据级别它没有。调用方按"没有通道"处理,不降级成全库。"""


def _uses_postgres(session: AsyncSession) -> bool:
    return session.get_bind().dialect.name == "postgresql"


async def set_tenant(session: AsyncSession, tenant: str) -> None:
    """把租户写进本条事务的会话变量。

    必须是事务本地:只在当前事务里有效,事务结束就复位,连接回池时不带着上一个租户。
    会话级的 `SET` 会把租户留在连接上,下一个借到这条连接的事务就看见了别人的账——
    这类错误在单测里很难出现,只在并发下出现。

    `set_config(name, value, true)` 是同一件事的绑定参数写法(`true` = 事务本地),
    租户值因此不必拼进 SQL;变量名是模块常量。
    """
    if not _uses_postgres(session):
        return
    await session.execute(
        text(f"SELECT set_config('{TENANT_SETTING}', :tenant, true)"),
        {"tenant": tenant},
    )


@asynccontextmanager
async def plugin_session(
    *, scopes: tuple[str, ...] | list[str], tenant: str, write: bool = False
) -> AsyncIterator[AsyncSession]:
    """给插件一条只在本租户内可见的会话。

    - 只读请求要求清单声明过 `read:own` 或 `write:own`;写请求要求 `write:own`;
    - 事务里 `SET LOCAL` 租户,库侧的 RLS 策略据此收口;
    - 会话用完即关,不把连接交给插件带走。

    没有声明就不给会话。这是**结构强制**的那一层:调用方拿不到 session,写不出
    "先看一眼是不是有权限,没有就照样查"的分支。
    """
    granted = set(scopes or ())
    needed = WRITE_SCOPES if write else (READ_SCOPES | WRITE_SCOPES)
    if not (granted & needed):
        raise DataScopeError(
            f"插件没有声明 {'/'.join(sorted(needed))} 级别的数据权限,不给库会话"
        )
    if write and "write:own" not in granted:
        raise DataScopeError("插件只声明了只读数据权限,不能拿写会话")

    from engine.db.engine import async_session_factory

    async with async_session_factory() as session:
        try:
            await set_tenant(session, tenant)
            yield session
        finally:
            await session.rollback()


class PluginData:
    """交给插件实例的一份数据通道。`execute_task` 的 `ctx.data` 就是它。

    形状刻意做成"要什么级别就声明什么级别、每次给一条短会话",不提供常驻连接:
    常驻连接会把"事务结束复位租户"这条保证弄丢。
    """

    def __init__(self, *, scopes: tuple[str, ...] | list[str], tenant: str) -> None:
        self.scopes = tuple(scopes or ())
        self.tenant = tenant

    def can(self, scope: str) -> bool:
        return scope in self.scopes

    @asynccontextmanager
    async def read(self) -> AsyncIterator[AsyncSession]:
        async with plugin_session(scopes=self.scopes, tenant=self.tenant) as session:
            yield session

    @asynccontextmanager
    async def write(self) -> AsyncIterator[AsyncSession]:
        async with plugin_session(
            scopes=self.scopes, tenant=self.tenant, write=True
        ) as session:
            yield session


__all__ = [
    "DataScopeError",
    "PluginData",
    "TENANT_SETTING",
    "plugin_session",
    "set_tenant",
]
