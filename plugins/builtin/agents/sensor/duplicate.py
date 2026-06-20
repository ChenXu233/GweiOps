# plugins/builtin/agents/sensor/duplicate.py
from dataclasses import dataclass
from engine.llm.embedding import EmbeddingService, SearchResult


@dataclass
class DuplicateResult:
    is_duplicate: bool
    similar_issue_id: int | None
    score: float


class DuplicateDetector:
    """检测重复 Issue。支持向量搜索和文本相似度。"""

    def __init__(self, threshold: float = 0.8, embedding_service: EmbeddingService | None = None):
        self.threshold = threshold
        self.embedding_service = embedding_service

    async def detect_async(
        self,
        title: str,
        body: str,
        existing_issues: list[dict],
    ) -> DuplicateResult:
        """异步检测是否存在重复 Issue。使用向量搜索。"""
        if not existing_issues:
            return DuplicateResult(is_duplicate=False, similar_issue_id=None, score=0.0)

        combined = f"{title} {body}"

        if self.embedding_service:
            # 使用向量搜索
            return await self._detect_with_vectors(combined, existing_issues)
        else:
            # 回退到文本相似度
            return self.detect(title, body, existing_issues)

    def detect(
        self,
        title: str,
        body: str,
        existing_issues: list[dict],
    ) -> DuplicateResult:
        """同步检测是否存在重复 Issue。使用文本相似度。"""
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

    async def _detect_with_vectors(
        self,
        text: str,
        existing_issues: list[dict],
    ) -> DuplicateResult:
        """使用向量搜索检测重复。"""
        # 1. 生成查询向量
        query_embedding = await self.embedding_service.embed_text(text)

        # 2. 准备现有 Issue 的向量
        existing_embeddings = []
        for issue in existing_issues:
            existing_text = f"{issue['title']} {issue['body']}"
            # 如果 Issue 已有向量，直接使用
            if "embedding" in issue and issue["embedding"]:
                existing_embeddings.append({
                    "id": issue["id"],
                    "embedding": issue["embedding"],
                })
            else:
                # 否则生成向量
                embedding = await self.embedding_service.embed_text(existing_text)
                existing_embeddings.append({
                    "id": issue["id"],
                    "embedding": embedding,
                })

        # 3. 搜索最相似的 Issue
        if not existing_embeddings:
            return DuplicateResult(is_duplicate=False, similar_issue_id=None, score=0.0)

        # 计算相似度
        best_score = 0.0
        best_issue_id = None

        for item in existing_embeddings:
            score = self.embedding_service.cosine_similarity(query_embedding, item["embedding"])
            if score > best_score:
                best_score = score
                best_issue_id = item["id"]

        is_duplicate = best_score >= self.threshold

        return DuplicateResult(
            is_duplicate=is_duplicate,
            similar_issue_id=best_issue_id if is_duplicate else None,
            score=best_score,
        )

    def _calculate_similarity(self, text_a: str, text_b: str) -> float:
        """计算两个文本的相似度。基于 Jaccard 相似度。"""
        words_a = set(text_a.split())
        words_b = set(text_b.split())

        if not words_a or not words_b:
            return 0.0

        intersection = words_a & words_b
        union = words_a | words_b

        return len(intersection) / len(union)
