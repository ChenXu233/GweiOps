# engine/change_unit/model.py
"""变更单元的字段。撤销的原子性由单元粒度保证(一个单元一个效果),不由事务保证。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# 撤销的两种来源。retained:依赖下游保留的旧状态(revision / snapshot);
# symmetric:靠对称操作撤销(缩回、重启),不需要保留物。
UNDO_RETAINED = "retained"
UNDO_SYMMETRIC = "symmetric"
UNDO_KINDS = (UNDO_RETAINED, UNDO_SYMMETRIC)

VERDICT_PENDING = "pending"
VERDICT_KEPT = "kept"  # 已验证,进入待审,仍可撤
VERDICT_ROLLED_BACK = "rolled_back"
VERDICT_BLOCKED = "blocked"  # 未执行,等人
VERDICT_IRREVERSIBLE = "irreversible"  # 已执行但拿不到句柄


@dataclass(frozen=True)
class Window:
    """还能撤回多久。

    unbounded=True 表示窗口不是一个时长,而是"目标还在就一直能撤"(对称撤销)。
    两者都没有 = unknown,一律当不可逆。
    """

    seconds: int | None = None
    unbounded: bool = False
    source: str = ""

    @property
    def known(self) -> bool:
        return self.unbounded or self.seconds is not None

    def covers(self, human_response_s: int) -> bool:
        if self.unbounded:
            return True
        return self.seconds is not None and self.seconds >= human_response_s


@dataclass(frozen=True)
class Effect:
    """一次下游调用 + 它的撤销方式。全部是引用,没有平台实现。"""

    task: str
    args: dict[str, Any]
    undo_task: str
    undo_kind: str = UNDO_RETAINED
    label: str = ""
    capability: str = ""  # 解析提供者用;由插件在声明里给出

    def __post_init__(self) -> None:
        if self.undo_kind not in UNDO_KINDS:
            raise ValueError(f"非法 undo_kind: {self.undo_kind}")


@dataclass
class ChangeUnit:
    """一次意图 + 一个效果 + 一个绑定 + 一个句柄 + 一个判定。

    binding 是这次变更作用的下游目标(哪台主机、哪个集群、哪个租户的实例)。
    平台不得假设自己与下游同机:没有 binding 的单元不可执行。
    """

    intent: dict[str, Any]
    effect: Effect
    tenant: str = ""
    binding: str = ""
    idempotency_key: str = ""  # 这次效果的身份;重放时据此复用既有结论
    handle: str | None = None
    window: Window | None = None
    verdict: str = VERDICT_PENDING
    reason: str = ""
    facts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["effect"] = {
            "task": self.effect.task,
            "args": self.effect.args,
            "undo_task": self.effect.undo_task,
            "undo_kind": self.effect.undo_kind,
            "label": self.effect.label,
            "capability": self.effect.capability,
        }
        return data
