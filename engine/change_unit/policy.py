# engine/change_unit/policy.py
"""策略即预授权:夜里哪些变更可以直接做,不用先等人点头。

策略回答两个问题,一个算得出,一个只能查:

1. 人到能赶回来的时候,还撤得回来吗。窗口与响应时延相比——三个参数量的是同一件事:
   响应时延本身(一个人 8 小时,三班倒 15 分钟)、无人值守时段(周五 18:00 之后是到周一早上)、
   放行范围(哪几类能力允许走这条路;空 = 不按能力限制)。
2. 这个动作以前在这台下游身上留下过什么。账本里的履历——同一类变更失败得够多,
   就不再夜间自动做,改为人看一眼。

"沉默默认"没有实现:它需要一个到点就会触发的调度器,而现在没有。
在调度器出现之前写进策略里,只是一个不会执行的参数。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .model import ChangeUnit, Window
from .record import TrackRecord

EXECUTE = "execute"
BLOCK = "block"

# 一个人的默认值:睡一觉,8 小时。窗口盖不住这 8 小时的,"随时可撤"对睡着的人不成立。
DEFAULT_HUMAN_RESPONSE_S = 8 * 3600


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
        return "无上限"
    if window.seconds is not None:
        return _duration(window.seconds)
    return "未知"


@dataclass(frozen=True)
class AwayWindow:
    """每周固定无人值守的时段,默认周五 18:00 → 周一 09:00。

    落在窗口里时,人的响应时延不是一个常量,而是"到窗口结束还有多久"。
    这样周五傍晚那次发布不需要额外一条禁令——它盖不住整整一个周末,自然被阻断。
    """

    start_weekday: int = 4  # 0=周一
    start_hour: int = 18
    end_weekday: int = 0
    end_hour: int = 9

    @property
    def start_min(self) -> int:
        return self.start_weekday * 1440 + self.start_hour * 60

    @property
    def end_min(self) -> int:
        return self.end_weekday * 1440 + self.end_hour * 60

    def contains(self, at: datetime) -> bool:
        minute = at.weekday() * 1440 + at.hour * 60 + at.minute
        start, end = self.start_min, self.end_min
        if start == end:
            return False
        if start < end:
            return start <= minute < end
        # 跨周末:窗口"绕过"周界,周一早上那一段也算在里面
        return minute >= start or minute < end

    def ends_at(self, at: datetime) -> datetime:
        """这个时段下一次结束的时刻(本地时区按 at 自己的时区算)。"""
        base = at.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=at.weekday())
        end = base + timedelta(minutes=self.end_min)
        while end <= at:
            end += timedelta(days=7)
        return end


@dataclass(frozen=True)
class Decision:
    """一次路径判定。reason 会被原样写进账本——人早上看到的就是这句话。"""

    action: str
    reason: str
    response_s: int = 0


@dataclass(frozen=True)
class Policy:
    human_response_s: int = DEFAULT_HUMAN_RESPONSE_S
    away: AwayWindow | None = field(default_factory=AwayWindow)
    allow_capabilities: tuple[str, ...] = ()
    # 履历门槛:少于这么多次就先不下结论;0 表示不看履历。
    history_min_attempts: int = 3
    history_max_failure_rate: float = 0.5

    def response_seconds(self, at: datetime) -> int:
        """此刻人的响应时延。落在无人值守时段里,答案是"到那之后"。"""
        if self.away is not None and self.away.contains(at):
            return max(1, int((self.away.ends_at(at) - at).total_seconds()))
        return self.human_response_s

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
        at: datetime,
        record: TrackRecord | None = None,
    ) -> Decision:
        """走第一类路径还是阻断。没有第三种答案。"""
        capability = unit.effect.capability
        if self.allow_capabilities and capability not in self.allow_capabilities:
            return Decision(
                BLOCK,
                f"能力 {capability or '(未声明)'} 不在夜间放行范围",
            )

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

        response_s = self.response_seconds(at)
        if not window.covers(response_s):
            where = ""
            if self.away is not None and self.away.contains(at):
                where = f"(无人值守至 {self.away.ends_at(at):%m-%d %H:%M})"
            return Decision(
                BLOCK,
                f"窗口 {window_label(window)} 盖不住人的响应时延 {_duration(response_s)}{where}",
                response_s,
            )

        return Decision(
            EXECUTE,
            f"窗口 {window_label(window)} 覆盖响应时延 {_duration(response_s)}",
            response_s,
        )
