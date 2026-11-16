# engine/plugin_manager/context.py
"""插件执行时拿到的上下文 —— 谁在什么租户上、要它干什么。

在这之前 `execute_task(task, params)` 只有两个位置参数,插件想知道"现在服务哪个
租户""谁让我做的",只能从 `params` 里翻,或者干脆 `from engine.db import ...`
自己去连库(那就是全库权限)。

`ctx` 把这几件事说清楚,并且**只给得出这几件**:租户、资源、调用者、手上的数据
级别。它不携带连接串、不携带密钥,插件能要到的库通道是 `ctx.data`,而 `ctx.data`
每次只发一条按租户收口的事务会话。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .data import PluginData


@dataclass(frozen=True)
class PluginContext:
    """一次能力调用的上下文。

    - `tenant`:这次调用服务哪个租户。空串是控制面(不针对具体租户);
    - `binding`:下游目标名。空串表示这个能力不绑在具体资源上;
    - `actor`:谁发起的(用户名或令牌名)。审计用,不是授权依据——授权在闸门与出口;
    - `scopes`:被调用插件清单里声明过的 `data.scopes`;
    - `capability`:这次调的是哪个能力,插件按它选任务名;
    - `incident_id` / `workflow_id`:便于插件把日志与账本对上号。
    """

    tenant: str = ""
    binding: str = ""
    actor: str = ""
    scopes: tuple[str, ...] = ()
    capability: str = ""
    incident_id: str = ""
    workflow_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def data(self) -> PluginData:
        """本次调用可用的数据通道。没有声明就拿到一个"什么都要不到"的通道。"""
        return PluginData(scopes=self.scopes, tenant=self.tenant)

    def can(self, scope: str) -> bool:
        return scope in self.scopes


def context_for(
    *,
    tenant: str = "",
    binding: str = "",
    actor: str = "",
    scopes: tuple[str, ...] | list[str] = (),
    capability: str = "",
    incident_id: str = "",
    workflow_id: str = "",
    extra: dict[str, Any] | None = None,
) -> PluginContext:
    return PluginContext(
        tenant=tenant or "",
        binding=binding or "",
        actor=actor or "",
        scopes=tuple(scopes or ()),
        capability=capability,
        incident_id=incident_id or "",
        workflow_id=workflow_id or "",
        extra=dict(extra or {}),
    )


async def execute(provider: Any, task: str, params: dict, ctx: PluginContext) -> dict:
    """把 `ctx` 交给插件,但对只实现两参 `execute_task` 的插件保持兼容。

    兼容不是留条后路:进程外代理与老内置插件都写在两参签名上,一次性全改会让
    一次改动同时动到 wire 契约与几十个实现。判据是签名里有没有第三个参数,
    用 `inspect` 读一次就够,不做 try/except TypeError——那会把插件内部的
    `TypeError` 也误判成"签名不对"。
    """
    handler = provider.execute_task
    try:
        arity = _positional_arity(handler)
    except (TypeError, ValueError):  # pragma: no cover - 内建/装饰器挡住签名时按新签名
        arity = 3
    if arity >= 3:
        return await handler(task, params, ctx)
    return await handler(task, params)


def _positional_arity(handler: Any) -> int:
    """这个可调用对象最多接几个位置参数(不含 self)。"""
    import inspect

    signature = inspect.signature(handler)
    count = 0
    for parameter in signature.parameters.values():
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            count += 1
        elif parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            return 99
    return count


__all__ = ["PluginContext", "context_for", "execute"]
