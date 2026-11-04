# engine/change_unit/runner.py
"""单元的推进:预读窗口 → 执行 → 后读窗口 → 验证 → 保持或回滚。

平台只做这四步判定;执行、撤销、取数、验证全部委托给 provider(插件)。
provider 声明自己服务的 binding,与单元不一致时拒绝执行——跨环境执行是事故,不是配置错。
"""

from __future__ import annotations

from typing import Any, Protocol

from .ledger import JsonlLedger
from .model import (
    ChangeUnit,
    Effect,
    Window,
    VERDICT_BLOCKED,
    VERDICT_IRREVERSIBLE,
    VERDICT_KEPT,
    VERDICT_ROLLED_BACK,
)

# 夜间人的响应时延。窗口小于它,"可回滚"对一个睡着的人不成立。
HUMAN_RESPONSE_S = 8 * 3600


class EffectProvider(Protocol):
    binding: str

    async def execute(self, task: str, args: dict[str, Any]) -> dict[str, Any]: ...

    async def undo(self, task: str, args: dict[str, Any], handle: str) -> dict[str, Any]: ...

    async def window(self, effect: Effect, handle: str | None) -> Window: ...

    async def verify(self, effect: Effect, handle: str) -> tuple[bool, dict[str, Any]]: ...


def _record(ledger: JsonlLedger | None, unit: ChangeUnit) -> None:
    if ledger is not None:
        ledger.append(unit)


def _assert_binding(unit: ChangeUnit, provider: EffectProvider) -> None:
    if not unit.binding:
        raise ValueError("单元没有 binding:不知道这次变更作用在哪个下游,拒绝执行")
    provider_binding = getattr(provider, "binding", "")
    if provider_binding != unit.binding:
        raise ValueError(
            f"binding 不匹配:单元={unit.binding!r} 提供者={provider_binding!r}"
        )
    # 提供者 tenant="" 表示它不按租户隔离(例如一个 GitHub 适配器服务所有租户)。
    provider_tenant = getattr(provider, "tenant", "")
    if provider_tenant not in ("", unit.tenant):
        raise ValueError(
            f"tenant 不匹配:单元={unit.tenant!r} 提供者={provider_tenant!r}"
        )


def _replay(unit: ChangeUnit, ledger: JsonlLedger | None) -> ChangeUnit | None:
    """带幂等键的单元重放时,沿用账本里的既有结论,不二次外呼。

    DBOS 只保证 at-least-once:进程在"做完"和"记账"之间崩溃,恢复后这一步会重跑。
    幂等必须由账本兜住,不能靠内存。
    """
    if not unit.idempotency_key:
        return None
    if ledger is None:
        raise ValueError("单元带幂等键但没有账本:无法判断是否已经执行过")
    row = ledger.find(unit.idempotency_key)
    if row is None:
        return None
    unit.handle = row.get("handle")
    unit.verdict = row.get("verdict") or unit.verdict
    unit.facts = row.get("facts") or {}
    unit.reason = f"重放:沿用既有结论({row.get('reason') or ''})"
    return unit


def _resolve_target(unit: ChangeUnit, target: Any) -> EffectProvider:
    """target 可以是注册表,也可以是一个已解析的 provider。

    给注册表时按 (租户, 目标) 精确解析;解析不到直接抛,不回退。
    """
    if hasattr(target, "resolve") and callable(getattr(target, "resolve")):
        capability = unit.effect.capability
        if not capability:
            raise ValueError("单元没有 capability,无法按目标解析提供者")
        if not unit.binding:
            raise ValueError("单元没有 binding:不知道这次变更作用在哪个下游,拒绝执行")
        return target.resolve(capability, tenant=unit.tenant, binding=unit.binding)
    return target


async def apply(
    unit: ChangeUnit, target: Any, ledger: JsonlLedger | None = None
) -> ChangeUnit:
    """推进一个单元。target 是已解析的 provider,或一个能 resolve 的注册表。"""
    replayed = _replay(unit, ledger)
    if replayed is not None:
        return replayed
    provider = _resolve_target(unit, target)
    _assert_binding(unit, provider)
    effect = unit.effect

    pre = await provider.window(effect, None)
    unit.window = pre
    if not pre.covers(HUMAN_RESPONSE_S):
        unit.verdict = VERDICT_BLOCKED
        unit.reason = f"执行前窗口不足: {pre.source or 'unknown'}"
        _record(ledger, unit)
        return unit

    result = await provider.execute(effect.task, effect.args)
    handle = result.get("handle")
    if not handle:
        # 已经动了外部世界,但兑现不了撤销:显式记为不可逆,不允许掩盖。
        unit.verdict = VERDICT_IRREVERSIBLE
        unit.reason = "执行后没有句柄,无法兑现撤销"
        unit.facts = {k: v for k, v in result.items() if k != "handle"}
        _record(ledger, unit)
        return unit
    unit.handle = handle

    post = await provider.window(effect, handle)
    unit.window = post
    if not post.covers(HUMAN_RESPONSE_S):
        await provider.undo(effect.undo_task, effect.args, handle)
        unit.verdict = VERDICT_ROLLED_BACK
        unit.reason = f"执行后窗口不足: {post.source or 'unknown'}"
        _record(ledger, unit)
        return unit

    ok, facts = await provider.verify(effect, handle)
    unit.facts = facts
    if not ok:
        await provider.undo(effect.undo_task, effect.args, handle)
        unit.verdict = VERDICT_ROLLED_BACK
        unit.reason = "验证未通过,已回滚"
        _record(ledger, unit)
        return unit

    unit.verdict = VERDICT_KEPT
    unit.reason = "验证通过,进入待审(可撤)"
    _record(ledger, unit)
    return unit


async def rollback(
    unit: ChangeUnit,
    target: Any,
    ledger: JsonlLedger | None = None,
    reason: str = "人工回滚",
) -> ChangeUnit:
    """人对账本按下撤销。没有句柄的单元不允许伪造回滚。"""
    provider = _resolve_target(unit, target)
    _assert_binding(unit, provider)
    if not unit.handle:
        raise ValueError("没有句柄的单元无法回滚")
    await provider.undo(unit.effect.undo_task, unit.effect.args, unit.handle)
    unit.verdict = VERDICT_ROLLED_BACK
    unit.reason = reason
    _record(ledger, unit)
    return unit
