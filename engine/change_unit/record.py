# engine/change_unit/record.py
"""履历 —— 把账本里已有的结论按"同一类变更"聚一次。

策略原来只回答一个问题:人到能赶回来的时候,还撤得回来吗。
它答不了另一个同样要紧的问题:**这个动作在这台下游身上,以前留下过什么结果。**

同样一段窗口,连续二十次全成和连续三次全回滚不是一回事:前者夜里直接做,
后者该有人看一眼。这份证据来自账本,不来自模型——所以可以复算、可以审计、
可以被人拿着账本推翻。

分母只算真正动过外部世界的单元。阻断和否决没有碰过下游,把它们算成失败,
等于因为"正确地拦住了"而永久怀疑这个能力。

failed 同样不进分母:它说的是"这次确定没碰到下游",对手上这个动作安不安全
没有任何信息量。但它是另一回事,所以单独计数——一个能力反复 failed 说明
配置或凭据坏了,那是给人看的信号,不是阻断的依据。

unknown 进分母,也进失败数:动没动都不知道,比已知撤不回来更说不清。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .model import (
    VERDICT_BLOCKED,
    VERDICT_FAILED,
    VERDICT_IRREVERSIBLE,
    VERDICT_KEPT,
    VERDICT_ROLLED_BACK,
    VERDICT_UNKNOWN,
    VERDICT_VETOED,
)

# 履历看最近多少次。太久以前的失败不该永远拖住一个能力,但也别只看最后一次。
DEFAULT_LOOKBACK = 50

# 动过外部世界的结论。unknown 也算:不知道动没动,不能当成没动。
_EXECUTED = (VERDICT_KEPT, VERDICT_ROLLED_BACK, VERDICT_IRREVERSIBLE, VERDICT_UNKNOWN)


@dataclass(frozen=True)
class TrackRecord:
    """同类变更(同租户、同下游、同能力)的履历。"""

    tenant: str = ""
    binding: str = ""
    capability: str = ""
    attempts: int = 0  # 动过下游的次数,失败率的分母
    kept: int = 0
    rolled_back: int = 0
    irreversible: int = 0
    unknown: int = 0  # 动没动不知道,进分母也进失败数
    blocked: int = 0  # 只是给人看的,不进分母
    vetoed: int = 0
    failed: int = 0  # 确定没动,不进分母;反复 failed 说明凭据或配置坏了
    last_verdict: str = ""
    last_reason: str = ""

    @property
    def failures(self) -> int:
        """动过下游但没留下好结果的次数。

        撤不回来比撤回来更糟,但不混成一类:账本里它们是两种结论。
        """
        return self.rolled_back + self.irreversible + self.unknown

    @property
    def failure_rate(self) -> float:
        if not self.attempts:
            return 0.0
        return self.failures / self.attempts

    @property
    def empty(self) -> bool:
        return self.attempts == 0


def _capability(row: dict[str, Any]) -> str:
    effect = row.get("effect")
    if not isinstance(effect, dict):
        return ""
    return str(effect.get("capability") or "")


def summarize(
    rows: Iterable[dict[str, Any]],
    *,
    binding: str = "",
    capability: str = "",
    tenant: str | None = None,
    lookback: int = DEFAULT_LOOKBACK,
) -> TrackRecord:
    """把账本行聚成履历。行来自 ledger.latest(),最新在前。

    binding 与 capability 为空表示不按它筛。没有 binding 的单元本来就拒绝执行,
    所以空串不会和真实的过滤值撞上。tenant 用 None 表示不筛——空串是一个真实租户。
    """
    picked: list[dict[str, Any]] = []
    for row in rows:
        if tenant is not None and row.get("tenant") != tenant:
            continue
        if binding and row.get("binding") != binding:
            continue
        if capability and _capability(row) != capability:
            continue
        picked.append(row)
        if lookback > 0 and len(picked) >= lookback:
            break

    counts = {
        VERDICT_KEPT: 0,
        VERDICT_ROLLED_BACK: 0,
        VERDICT_IRREVERSIBLE: 0,
        VERDICT_UNKNOWN: 0,
        VERDICT_BLOCKED: 0,
        VERDICT_VETOED: 0,
        VERDICT_FAILED: 0,
    }
    for row in picked:
        verdict = row.get("verdict") or ""
        if verdict in counts:
            counts[verdict] += 1

    last = next((row for row in picked if (row.get("verdict") or "") in _EXECUTED), None)

    return TrackRecord(
        tenant=tenant if tenant is not None else "",
        binding=binding,
        capability=capability,
        attempts=sum(counts[v] for v in _EXECUTED),
        kept=counts[VERDICT_KEPT],
        rolled_back=counts[VERDICT_ROLLED_BACK],
        irreversible=counts[VERDICT_IRREVERSIBLE],
        unknown=counts[VERDICT_UNKNOWN],
        blocked=counts[VERDICT_BLOCKED],
        vetoed=counts[VERDICT_VETOED],
        failed=counts[VERDICT_FAILED],
        last_verdict=(last or {}).get("verdict", ""),
        last_reason=(last or {}).get("reason", ""),
    )


async def track_record(
    ledger: Any,
    *,
    tenant: str = "",
    binding: str = "",
    capability: str = "",
    lookback: int = DEFAULT_LOOKBACK,
) -> TrackRecord | None:
    """从账本取履历。没有账本就返回 None。

    None 的含义是"不知道",不是"没问题":调用方不得把缺证据当成好证据。
    """
    if ledger is None:
        return None
    rows = await ledger.latest(tenant=tenant)
    return summarize(
        rows,
        binding=binding,
        capability=capability,
        tenant=tenant,
        lookback=lookback,
    )


__all__ = ["TrackRecord", "summarize", "track_record", "DEFAULT_LOOKBACK"]
