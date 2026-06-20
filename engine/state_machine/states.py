# engine/state_machine/states.py
from enum import Enum


class WorkflowState(str, Enum):
    """工作流状态定义"""
    S0_PERCEIVED = "S0_PERCEIVED"   # 问题感知
    S1_DIAGNOSED = "S1_DIAGNOSED"   # 诊断决策
    S2_PLANNED = "S2_PLANNED"       # 方案生成
    S3_EXECUTED = "S3_EXECUTED"     # 方案执行
    S4_VERIFIED = "S4_VERIFIED"     # 验证
    S5_CANARIED = "S5_CANARIED"     # 生产分流
    S6_REVIEWED = "S6_REVIEWED"     # 最终审核
    DONE = "DONE"                   # 完成
    FAILED = "FAILED"               # 失败


class IssueType(str, Enum):
    """Issue 类型"""
    BUG = "bug"
    FEATURE = "feature"
    DOCS = "docs"
    DUPLICATE = "duplicate"
    QUESTION = "question"
    UNKNOWN = "unknown"


class ActionType(str, Enum):
    """行动类型"""
    CODE_FIX = "code_fix"           # 代码修复
    UPSTREAM_UPDATE = "upstream_update"  # 上游更新
    NON_CODE_ACTION = "non_code_action"  # 非代码运维
