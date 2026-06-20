# src/services/embedding.py
import math
from dataclasses import dataclass


@dataclass
class SearchResult:
    """搜索结果数据类。"""
    id: str
    score: float
    content: str
    metadata: dict | None = None


class EmbeddingService:
    """向量嵌入服务，提供文本向量化和相似度搜索功能。"""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key
        self._dimension = 1536  # OpenAI text-embedding-3-small 默认维度

    async def embed_text(self, text: str) -> list[float]:
        """将单个文本转换为向量。"""
        return await self._call_embedding_api(text)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量将文本转换为向量。"""
        if not texts:
            return []

        # 调用批量嵌入 API
        return await self._call_embedding_api(texts)

    def cosine_similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """计算两个向量的余弦相似度。"""
        if len(vec_a) != len(vec_b):
            raise ValueError("向量维度必须相同")

        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    async def search(
        self,
        query: str,
        vectors: list[dict],
        top_k: int = 5,
    ) -> list[SearchResult]:
        """在向量集合中搜索最相似的向量。

        Args:
            query: 查询文本
            vectors: 向量列表，每个元素包含 id, embedding, content, metadata
            top_k: 返回前k个最相似的结果

        Returns:
            搜索结果列表，按相似度降序排列
        """
        query_vector = await self.embed_text(query)

        scores = []
        for item in vectors:
            score = self.cosine_similarity(query_vector, item["embedding"])
            scores.append((score, item))

        # 按相似度降序排序
        scores.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, item in scores[:top_k]:
            results.append(
                SearchResult(
                    id=item["id"],
                    score=score,
                    content=item.get("content", ""),
                    metadata=item.get("metadata"),
                )
            )

        return results

    async def _call_embedding_api(self, text_or_texts: str | list[str]) -> list[float] | list[list[float]]:
        """调用嵌入 API。简化实现：返回模拟向量。"""
        # 简化实现：基于文本生成一个伪向量
        # 实际应该调用 OpenAI 或其他嵌入 API
        import hashlib

        if isinstance(text_or_texts, str):
            # 单个文本
            text = text_or_texts
            hash_bytes = hashlib.sha256(text.encode()).digest()

            # 生成 1536 维的伪向量
            vector = []
            for i in range(self._dimension):
                byte_index = i % len(hash_bytes)
                # 归一化到 [-1, 1] 范围
                value = (hash_bytes[byte_index] / 127.5) - 1.0
                vector.append(value)

            return vector
        else:
            # 批量文本
            texts = text_or_texts
            results = []
            for text in texts:
                hash_bytes = hashlib.sha256(text.encode()).digest()

                # 生成 1536 维的伪向量
                vector = []
                for i in range(self._dimension):
                    byte_index = i % len(hash_bytes)
                    # 归一化到 [-1, 1] 范围
                    value = (hash_bytes[byte_index] / 127.5) - 1.0
                    vector.append(value)

                results.append(vector)

            return results