# engine/change_unit/runner.py
"""单元的推进:预读窗口 → 查履历 → 判定路径 → 执行 → 后读窗口 → 验证 → 保持或回滚。

平台只做判定;执行、撤销、取数、验证全部委托给 provider(插件)。
provider 声明自己服务的 binding,与单元不一致时拒绝执行——跨环境执行是事故,不是配置错。

阻断不是终点:人放行(approve)、人不做(veto)各写一行账,与自动执行一样可审计。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from .errors import EffectNotApplied
from .ledger import Ledger
from .model import (
    ChangeUnit,
    Effect,
    Window,
    VERDICT_BLOCKED,
    VERDICT_FAILED,
    VERDICT_IRREVERSIBLE,
    VERDICT_KEPT,
    VERDICT_ROLLED_BACK,
    VERDICT_UNKNOWN,
    VERDICT_VETOED,
)
from .policy import EXECUTE, DEFAULT_HUMAN_RESPONSE_S, Policy
from .record import track_record
from .undo import undo_state

# 旧的模块级常量,保留给已有调用方;真正的口径在 Policy.human_response_s。
HUMAN_RESPONSE_S = DEFAULT_HUMAN_RESPONSE_S


class EffectProvider(Protocol):
    binding: str

    # 抛 EffectNotApplied 表示确定没碰到下游(单元记 failed);抛别的异常一律按
    # unknown 处理 —— 请求可能已经到了对面,只有提供者知道是不是。
    async def execute(self, task: str, args: dict[str, Any]) -> dict[str, Any]: ...

    async def undo(self, task: str, args: dict[str, Any], handle: str) -> dict[str, Any]: ...

    async def window(self, effect: Effect, handle: str | None) -> Window: ...

    async def verify(self, effect: Effect, handle: str) -> tuple[bool, dict[str, Any]]: ...


async def _record(ledger: Ledger | None, unit: ChangeUnit) -> None:
    if ledger is not None:
        await ledger.append(unit)


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


async def _replay(unit: ChangeUnit, ledger: Ledger | None) -> ChangeUnit | None:
    """带幂等键的单元重放时,沿用账本里的既有结论,不二次外呼。

    DBOS 只保证 at-least-once:进程在"做完"和"记账"之间崩溃,恢复后这一步会重跑。
    幂等必须由账本兜住,不能靠内存。
    """
    if not unit.idempotency_key:
        return None
    if ledger is None:
        raise ValueError("单元带幂等键但没有账本:无法判断是否已经执行过")
    row = await ledger.find(unit.idempotency_key)
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


def _merge(unit: ChangeUnit, facts: dict[str, Any]) -> None:
    """执行结果、验证结果、放行记录都留在同一份 facts 里,别互相覆盖。"""
    unit.facts = {**unit.facts, **facts}


def _brief(exc: BaseException, limit: int = 200) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text if len(text) <= limit else text[:limit] + "…"


def _error_facts(stage: str, exc: BaseException) -> dict[str, Any]:
    """下游报错也是一条事实,按阶段存起来,别让它只活在日志里。"""
    return {
        "error": {
            "stage": stage,
            "type": type(exc).__name__,
            "message": str(exc)[:500],
        }
    }


async def _revert(
    unit: ChangeUnit,
    provider: EffectProvider,
    ledger: Ledger | None,
    why: str,
    *,
    ok_reason: str = "",
) -> ChangeUnit:
    """撤销本身也是一次外呼。撤不掉要如实说,不能记成撤掉了。"""
    try:
        await provider.undo(unit.effect.undo_task, unit.effect.args, unit.handle or "")
    except Exception as exc:
        unit.verdict = VERDICT_IRREVERSIBLE
        unit.reason = f"{why},撤销也失败: {_brief(exc)}"
        _merge(unit, _error_facts("undo", exc))
    else:
        unit.verdict = VERDICT_ROLLED_BACK
        unit.reason = ok_reason or f"{why},已回滚"
    await _record(ledger, unit)
    return unit


async def _run(
    unit: ChangeUnit,
    provider: EffectProvider,
    ledger: Ledger | None,
    *,
    policy: Policy,
    now: datetime,
    authorized_by: str,
) -> ChangeUnit:
    effect = unit.effect

    try:
        pre = await provider.window(effect, None)
    except Exception as exc:
        # 读不到就不能判:阻断的代价是人看一眼,放行的代价是夜里动了撤不回来的东西。
        unit.verdict = VERDICT_BLOCKED
        unit.reason = f"读窗口时下游报错,判不了可逆性,不执行: {_brief(exc)}"
        _merge(unit, _error_facts("window.pre", exc))
        await _record(ledger, unit)
        return unit
    unit.window = pre

    if authorized_by:
        # 人此刻在场的,窗口不需要盖过"睡一觉"的时间。
        _merge(unit, {"authorized_by": authorized_by})
        response_s = 0
    else:
        # 判定要用到"这类变更以前怎么样",所以先查一次履历;没有账本就是没有证据。
        record = None
        if policy.wants_history():
            record = await track_record(
                ledger,
                tenant=unit.tenant,
                binding=unit.binding,
                capability=effect.capability,
            )
        decision = policy.decide(unit, pre, now, record=record)
        if decision.action != EXECUTE:
            unit.verdict = VERDICT_BLOCKED
            unit.reason = decision.reason
            await _record(ledger, unit)
            return unit
        _merge(unit, {"gate": decision.reason})
        response_s = decision.response_s

    try:
        result = await provider.execute(effect.task, effect.args)
    except EffectNotApplied as exc:
        # 提供者认得出这次调用没碰到下游(构造请求就失败了,或下游明确拒绝)。
        # 那不是"不知道",是可以照原样重试的失败:不必等人,也不该占着待审清单。
        cause = exc.__cause__ or exc
        unit.verdict = VERDICT_FAILED
        unit.reason = f"下游确定没动,可以重试: {_brief(cause)}"
        _merge(unit, _error_facts("execute", cause))
        await _record(ledger, unit)
        return unit
    except Exception as exc:
        # 请求可能已经发出去了。当没发生是掩盖,当成功是撒谎:没有句柄就没有撤销,
        # 而连动没动都不知道的时候,唯一诚实的结论是 unknown。
        unit.verdict = VERDICT_UNKNOWN
        unit.reason = f"执行时下游报错,不知道动没动: {_brief(exc)}"
        _merge(unit, _error_facts("execute", exc))
        await _record(ledger, unit)
        return unit
    if not isinstance(result, dict):
        unit.verdict = VERDICT_IRREVERSIBLE
        unit.reason = f"执行结果不是对象({type(result).__name__}),拿不到句柄"
        await _record(ledger, unit)
        return unit
    handle = result.get("handle")
    if not handle:
        # 已经动了外部世界,但兑现不了撤销:显式记为不可逆,不允许掩盖。
        unit.verdict = VERDICT_IRREVERSIBLE
        unit.reason = "执行后没有句柄,无法兑现撤销"
        _merge(unit, {k: v for k, v in result.items() if k != "handle"})
        await _record(ledger, unit)
        return unit
    unit.handle = handle
    _merge(unit, {k: v for k, v in result.items() if k != "handle"})

    try:
        post = await provider.window(effect, handle)
    except Exception as exc:
        unit.verdict = VERDICT_IRREVERSIBLE
        unit.reason = f"已执行,但执行后读窗口报错,撤销兑现不了: {_brief(exc)}"
        _merge(unit, _error_facts("window.post", exc))
        await _record(ledger, unit)
        return unit
    unit.window = post
    # 人在场:只问"撤得了吗";人不在:要问"到他能反应过来时还撤得了吗"。
    still_reversible = post.known if authorized_by else post.covers(response_s)
    if not still_reversible:
        if post.known:
            return await _revert(
                unit, provider, ledger, f"执行后窗口不足: {post.source or 'unknown'}"
            )
        unit.verdict = VERDICT_IRREVERSIBLE
        unit.reason = "已执行,但执行后读不到窗口,撤销兑现不了"
        await _record(ledger, unit)
        return unit

    try:
        ok, facts = await provider.verify(effect, handle)
    except Exception as exc:
        # 验不了就不能说成了。窗口还在,回滚比留着更安全。
        _merge(unit, _error_facts("verify", exc))
        return await _revert(unit, provider, ledger, f"验证时下游报错: {_brief(exc)}")
    _merge(unit, facts)
    if not ok:
        return await _revert(unit, provider, ledger, "验证未通过")

    unit.verdict = VERDICT_KEPT
    unit.reason = "人工放行后验证通过,保持运行" if authorized_by else "验证通过,进入待审(可撤)"
    await _record(ledger, unit)
    return unit


async def apply(
    unit: ChangeUnit,
    target: Any,
    ledger: Ledger | None = None,
    *,
    policy: Policy | None = None,
    authorized_by: str = "",
    at: datetime | None = None,
    skip_replay: bool = False,
) -> ChangeUnit:
    """推进一个单元。target 是已解析的 provider,或一个能 resolve 的注册表。

    authorized_by 非空表示人已经当场放手:跳过路径判定,执行后仍照常读窗口、照常验证。
    at 只在测试里用,给策略一个确定的"现在"。
    skip_replay 只给放行用:被阻断的单元已经有同键记录,照幂等规则会被直接判成"已完成"。
    """
    if not skip_replay:
        replayed = await _replay(unit, ledger)
        if replayed is not None:
            return replayed
    provider = _resolve_target(unit, target)
    _assert_binding(unit, provider)
    return await _run(
        unit,
        provider,
        ledger,
        policy=policy or Policy(),
        now=at or datetime.now(timezone.utc),
        authorized_by=authorized_by,
    )


async def approve(
    unit: ChangeUnit,
    target: Any,
    ledger: Ledger | None = None,
    *,
    by: str = "",
    reason: str = "人工放行",
) -> ChangeUnit:
    """人对一个阻断的单元放手。

    放行不等于放宽判定口径:执行后照样读窗口、照样验证,失败照样回滚。
    它只说明"此刻有人在场",因此响应时延按秒算而不是按小时算。
    """
    if unit.verdict != VERDICT_BLOCKED:
        raise ValueError(f"只有阻断的单元需要放行,当前是 {unit.verdict!r}")
    _merge(unit, {"blocked_reason": unit.reason, "approval_reason": reason})
    # 放行是人在同一个幂等键上的一次新决定,不能被"上一次已经阻断"的账本短接。
    return await apply(
        unit,
        target,
        ledger,
        authorized_by=by or "人工",
        at=datetime.now(timezone.utc),
        skip_replay=True,
    )


async def veto(
    unit: ChangeUnit,
    ledger: Ledger | None = None,
    *,
    by: str = "",
    reason: str = "人工否决",
) -> ChangeUnit:
    """人不做这次变更。否决本身也是一次决定,同样写一行账。"""
    if unit.verdict in (VERDICT_KEPT, VERDICT_ROLLED_BACK):
        raise ValueError(f"单元已经执行过({unit.verdict!r}),只能撤销,不能否决")
    unit.verdict = VERDICT_VETOED
    unit.reason = reason
    if by:
        _merge(unit, {"vetoed_by": by})
    await _record(ledger, unit)
    return unit


async def rollback(
    unit: ChangeUnit,
    target: Any,
    ledger: Ledger | None = None,
    reason: str = "人工回滚",
    by: str = "",
) -> ChangeUnit:
    """人对账本按下撤销。没有句柄的单元不允许伪造回滚。"""
    provider = _resolve_target(unit, target)
    _assert_binding(unit, provider)
    if not unit.handle:
        raise ValueError("没有句柄的单元无法回滚")

    # 窗口过去了就不该再兑现撤销:下游保留的旧状态已经不在保证范围内。
    state = undo_state(unit.to_dict())
    if not state.undoable:
        raise ValueError(f"这次变更已经不能撤:{state.reason}")

    if by:
        _merge(unit, {"rolled_back_by": by})
    return await _revert(unit, provider, ledger, "撤销时下游报错", ok_reason=reason)