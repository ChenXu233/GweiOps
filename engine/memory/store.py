# engine/memory/store.py
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class MemoryRecord:
    """记忆记录"""
    id: str
    content: str
    embedding: List[float]
    metadata: Dict[str, Any]
    created_at: float


class MemoryStore:
    """向量存储"""

    def __init__(self):
        self.records: Dict[str, MemoryRecord] = {}

    async def add(self, record: MemoryRecord):
        """添加记录"""
        self.records[record.id] = record

    async def get(self, record_id: str) -> Optional[MemoryRecord]:
        """获取记录"""
        return self.records.get(record_id)

    async def delete(self, record_id: str):
        """删除记录"""
        if record_id in self.records:
            del self.records[record_id]

    async def search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        threshold: float = 0.7,
    ) -> List[MemoryRecord]:
        """搜索相似记录"""
        import math

        def cosine_similarity(a: List[float], b: List[float]) -> float:
            dot_product = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(x * x for x in b))
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot_product / (norm_a * norm_b)

        results = []
        for record in self.records.values():
            score = cosine_similarity(query_embedding, record.embedding)
            if score >= threshold:
                results.append((score, record))

        results.sort(key=lambda x: x[0], reverse=True)
        return [record for _, record in results[:top_k]]

    async def list_all(self) -> List[MemoryRecord]:
        """列出所有记录"""
        return list(self.records.values())

    async def count(self) -> int:
        """获取记录数量"""
        return len(self.records)
