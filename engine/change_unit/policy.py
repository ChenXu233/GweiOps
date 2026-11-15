# engine/change_unit/policy.py
"""策略即预授权:哪些能力可以不经人直接做。

契约见 docs/explanation/change-unit-contract.md 第 4 节:变更分两类——

- **自动收敛**:不需要人做价值判断,且能自己收敛(有句柄、读得到窗口、验证可判定)。
  这类做完继续跑,坏了 verify 会撤,没有人守在里面。
- **人在回路**:其余全部。执行前先阻断等人,而且没有超时。

这份策略只决定第一类:名单里的能力可以无人执行。**名单为空就是一律等人**——
要自动,先点名。名单里写 "*" 表示不筛,只给演示与测试用。

第二类不由策略决定:它压根不会被自动执行。
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import ChangeUnit, Window
from .record import TrackRecord

EXECUTE = "execute"
BLOCK = "block"


def _duration(seconds: int) -> str:
    if seconds >= 86400:
        days, rest = divmod(seconds, 86400)
        text = f"{days} 天"
        if rest // 3600:
            text += f" {rest // 3600} 小时"
        return text
    if seconds >= 3600:
        hours, rest = divmod(seconds, 3600)
        text = f"{hours} 小时"
        if rest // 60:
            text += f" {rest // 60} 分"
        return text
    return f"{seconds} 秒"


def window_label(window: Window) -> str:
    """给账本用的窗口说法。读不到就说读不到,不猜。"""
    if window.unbounded:
        if window.estimated:
            return "目标还在就能撤(按次数/容量淘汰,算不出到期)"
        return "目标还在就能撤"
    if window.seconds is not None:
        return _duration(window.seconds)
    return "读不到"


@dataclass(frozen=True)
class Decision:
    """一次路径判定。reason 会被原样写进账本——人看到的就是这句话。"""

    action: str
    reason: str


@dataclass(frozen=True)
class Policy:
    """自动收敛的范围,以及"这个动作以前在这台下游身上怎么样"的门槛。"""

    # 允许不经人执行的能力。空 = 一律等人;"*" = 不筛(演示与测试)。
    autonomous_capabilities: tuple[str, ...] = ()
    # 履历门槛:少于这么多次就先不下结论;0 表示不看履历。
    history_min_attempts: int = 3
    history_max_failure_rate: float = 0.5

    def allows_without_human(self, capability: str) -> bool:
        if not capability:
            return False
        if "*" in self.autonomous_capabilities:
            return True
        return capability in self.autonomous_capabilities

    def wants_history(self) -> bool:
        return self.history_min_attempts > 0

    def history_blocks(self, record: TrackRecord) -> bool:
        """履历够不够烂,烂到不该再由机器自己决定。"""
        if not self.wants_history() or record.attempts < self.history_min_attempts:
            return False
        return record.failure_rate >= self.history_max_failure_rate

    def decide(
        self,
        unit: ChangeUnit,
        window: Window,
        record: TrackRecord | None = None,
    ) -> Decision:
        """自动做,还是先等人。没有第三种答案。"""
        capability = unit.effect.capability
        if not self.allows_without_human(capability):
            return Decision(
                BLOCK,
                f"能力 {capability or '(未声明)'} 不在自动收敛范围:这类变更先等人",
            )

        # 窗口是"撤得回来"的唯一依据;读不到就不许自动做。
        if not window.known:
            return Decision(BLOCK, "窗口读不到,按不可逆处理")

        # 窗口只说明"撤得回来",不说明"撤回来的概率"。后者只能从账本里看。
        if record is not None and self.history_blocks(record):
            tail = f",上次:{record.last_reason}" if record.last_reason else ""
            return Decision(
                BLOCK,
                f"同类变更在 {unit.binding} 上已经失败 "
                f"{record.failures}/{record.attempts} 次{tail}",
            )

        return Decision(
            EXECUTE,
            f"能力 {capability} 已列入自动收敛范围,窗口 {window_label(window)}",
        )
