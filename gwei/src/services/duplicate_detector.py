# src/services/duplicate_detector.py
from dataclasses import dataclass


@dataclass
class DuplicateResult:
    is_duplicate: bool
    similar_issue_id: int | None
    score: float


class DuplicateDetector:
    """检测重复 Issue。"""

    def __init__(self, threshold: float = 0.8):
        self.threshold = threshold

    def detect(
        self,
        title: str,
        body: str,
        existing_issues: list[dict],
    ) -> DuplicateResult:
        """检测是否存在重复 Issue。

        简化版：基于文本相似度。生产环境使用向量搜索。
        """
        if not existing_issues:
            return DuplicateResult(is_duplicate=False, similar_issue_id=None, score=0.0)

        combined = f"{title} {body}".lower()
        best_score = 0.0
        best_issue_id = None

        for issue in existing_issues:
            existing_combined = f"{issue['title']} {issue['body']}".lower()
            score = self._calculate_similarity(combined, existing_combined)

            if score > best_score:
                best_score = score
                best_issue_id = issue["id"]

        is_duplicate = best_score >= self.threshold

        return DuplicateResult(
            is_duplicate=is_duplicate,
            similar_issue_id=best_issue_id if is_duplicate else None,
            score=best_score,
        )

    def _calculate_similarity(self, text_a: str, text_b: str) -> float:
        """计算两个文本的相似度。简化版：基于共同词数。"""
        words_a = set(text_a.split())
        words_b = set(text_b.split())

        if not words_a or not words_b:
            return 0.0

        intersection = words_a & words_b
        union = words_a | words_b

        return len(intersection) / len(union)
