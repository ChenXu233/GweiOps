# engine/memory/retriever.py
from typing import Dict, Any, List, Optional
from .store import MemoryStore, MemoryRecord


class MemoryRetriever:
    """记忆检索"""

    def __init__(self, store: MemoryStore):
        self.store = store

    async def retrieve(
        self,
        query: str,
        query_embedding: List[float],
        top_k: int = 5,
        threshold: float = 0.7,
    ) -> List[MemoryRecord]:
        """检索相关记忆"""
        return await self.store.search(query_embedding, top_k, threshold)

    async def retrieve_by_context(
        self,
        context: Dict[str, Any],
        query_embedding: List[float],
        top_k: int = 5,
    ) -> List[MemoryRecord]:
        """根据上下文检索记忆"""
        # 获取所有记录
        all_records = await self.store.list_all()

        # 根据上下文过滤
        filtered = []
        for record in all_records:
            if self._matches_context(record, context):
                filtered.append(record)

        # 按相似度排序
        import math

        def cosine_similarity(a: List[float], b: List[float]) -> float:
            dot_product = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(x * x for x in b))
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot_product / (norm_a * norm_b)

        scored = [
            (cosine_similarity(query_embedding, record.embedding), record)
            for record in filtered
        ]
        scored.sort(key=lambda x: x[0], reverse=True)

        return [record for _, record in scored[:top_k]]

    def _matches_context(self, record: MemoryRecord, context: Dict[str, Any]) -> bool:
        """检查记录是否匹配上下文"""
        for key, value in context.items():
            if key in record.metadata:
                if record.metadata[key] != value:
                    return False
        return True
