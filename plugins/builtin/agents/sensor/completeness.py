# src/services/completeness.py
from dataclasses import dataclass


@dataclass
class CompletenessReport:
    is_complete: bool
    missing_fields: list[str]
    score: float


class CompletenessChecker:
    """验证 Issue 的完整性。"""

    def __init__(self, required_fields: list[str] | None = None):
        self.required_fields = required_fields or ["reproduction", "expected", "actual"]

    def check(self, body: str) -> CompletenessReport:
        """检查 Issue body 是否包含必要字段。"""
        body_lower = body.lower()
        missing = []

        # 检查每个必需字段
        field_keywords = {
            "reproduction": ["reproduction", "复现", "steps to reproduce", "复现步骤"],
            "expected": ["expected", "期望", "期望行为", "expected behavior"],
            "actual": ["actual", "实际", "实际行为", "actual behavior"],
        }

        for field in self.required_fields:
            keywords = field_keywords.get(field, [field])
            if not any(kw in body_lower for kw in keywords):
                missing.append(field)

        # 计算完整性分数
        if not self.required_fields:
            score = 1.0
        else:
            score = 1.0 - (len(missing) / len(self.required_fields))

        return CompletenessReport(
            is_complete=len(missing) == 0,
            missing_fields=missing,
            score=score,
        )
