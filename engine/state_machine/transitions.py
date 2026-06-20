# engine/state_machine/transitions.py
from typing import Dict, Any, List, Optional
from .states import WorkflowState, ActionType


class TransitionRule:
    """状态转换规则"""

    def __init__(
        self,
        from_state: WorkflowState,
        to_state: WorkflowState,
        condition: str,
        description: str,
    ):
        self.from_state = from_state
        self.to_state = to_state
        self.condition = condition
        self.description = description


# 默认转换规则
DEFAULT_TRANSITIONS = [
    # S0 → S1: 问题感知后进入诊断
    TransitionRule(
        from_state=WorkflowState.S0_PERCEIVED,
        to_state=WorkflowState.S1_DIAGNOSED,
        condition="issue_perceived",
        description="问题感知后进入诊断决策",
    ),
    # S1 → S2: 诊断完成后生成方案
    TransitionRule(
        from_state=WorkflowState.S1_DIAGNOSED,
        to_state=WorkflowState.S2_PLANNED,
        condition="diagnosis_completed",
        description="诊断完成后生成修复方案",
    ),
    # S2 → S3: 方案生成后执行
    TransitionRule(
        from_state=WorkflowState.S2_PLANNED,
        to_state=WorkflowState.S3_EXECUTED,
        condition="plan_generated",
        description="方案生成后执行",
    ),
    # S3 → S4: 执行完成后验证
    TransitionRule(
        from_state=WorkflowState.S3_EXECUTED,
        to_state=WorkflowState.S4_VERIFIED,
        condition="execution_completed",
        description="执行完成后验证",
    ),
    # S4 → S5: 验证通过后生产分流
    TransitionRule(
        from_state=WorkflowState.S4_VERIFIED,
        to_state=WorkflowState.S5_CANARIED,
        condition="verification_passed",
        description="验证通过后生产分流",
    ),
    # S5 → S6: 金丝雀发布后最终审核
    TransitionRule(
        from_state=WorkflowState.S5_CANARIED,
        to_state=WorkflowState.S6_REVIEWED,
        condition="canary_completed",
        description="金丝雀发布后最终审核",
    ),
    # S6 → DONE: 审核通过后完成
    TransitionRule(
        from_state=WorkflowState.S6_REVIEWED,
        to_state=WorkflowState.DONE,
        condition="review_approved",
        description="审核通过后完成",
    ),
    # S6 → S2: 审核不通过，回退到方案生成
    TransitionRule(
        from_state=WorkflowState.S6_REVIEWED,
        to_state=WorkflowState.S2_PLANNED,
        condition="review_rejected",
        description="审核不通过，回退到方案生成",
    ),
    # 任意状态 → FAILED: 失败
    TransitionRule(
        from_state=WorkflowState.S0_PERCEIVED,
        to_state=WorkflowState.FAILED,
        condition="error_occurred",
        description="发生错误",
    ),
]
