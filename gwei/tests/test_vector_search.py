# tests/test_vector_search.py
import pytest
from unittest.mock import AsyncMock, patch
from src.services.duplicate_detector import DuplicateDetector
from src.services.embedding import EmbeddingService


@pytest.mark.asyncio
async def test_vector_search_basic():
    """测试基本向量搜索。"""
    embedding_service = EmbeddingService(api_key="test")
    detector = DuplicateDetector(threshold=0.8, embedding_service=embedding_service)

    # Mock 嵌入服务
    with patch.object(embedding_service, "embed_text", new_callable=AsyncMock) as mock_embed:
        with patch.object(embedding_service, "cosine_similarity", return_value=0.95) as mock_sim:
            mock_embed.return_value = [0.1] * 1536

            existing_issues = [
                {"id": 1, "title": "Parser crash", "body": "Crash on null input", "embedding": [0.1] * 1536},
            ]

            result = await detector.detect_async(
                title="Parser crash on null",
                body="The parser crashes when input is null",
                existing_issues=existing_issues,
            )

            assert result.is_duplicate is True
            assert result.score > 0.8


@pytest.mark.asyncio
async def test_vector_search_no_match():
    """测试向量搜索无匹配。"""
    embedding_service = EmbeddingService(api_key="test")
    detector = DuplicateDetector(threshold=0.8, embedding_service=embedding_service)

    with patch.object(embedding_service, "embed_text", new_callable=AsyncMock) as mock_embed:
        with patch.object(embedding_service, "cosine_similarity", return_value=0.3) as mock_sim:
            mock_embed.return_value = [0.1] * 1536

            existing_issues = [
                {"id": 1, "title": "Parser crash", "body": "Crash on null input", "embedding": [0.1] * 1536},
            ]

            result = await detector.detect_async(
                title="Add JSON support",
                body="Need JSON output format",
                existing_issues=existing_issues,
            )

            assert result.is_duplicate is False


@pytest.mark.asyncio
async def test_vector_search_generate_embeddings():
    """测试向量搜索时自动生成嵌入。"""
    embedding_service = EmbeddingService(api_key="test")
    detector = DuplicateDetector(threshold=0.8, embedding_service=embedding_service)

    with patch.object(embedding_service, "embed_text", new_callable=AsyncMock) as mock_embed:
        with patch.object(embedding_service, "cosine_similarity", return_value=0.9) as mock_sim:
            mock_embed.return_value = [0.1] * 1536

            # 现有 Issue 没有预计算的嵌入
            existing_issues = [
                {"id": 1, "title": "Parser crash", "body": "Crash on null input"},
            ]

            result = await detector.detect_async(
                title="Parser crash on null",
                body="The parser crashes when input is null",
                existing_issues=existing_issues,
            )

            # 应该调用 embed_text 生成嵌入
            assert mock_embed.call_count >= 2  # 一次查询 + 一次现有 Issue


def test_text_similarity_fallback():
    """测试文本相似度回退。"""
    detector = DuplicateDetector(threshold=0.8)

    existing_issues = [
        {"id": 1, "title": "Parser crash on null", "body": "The parser crashes when input is null"},
    ]

    result = detector.detect(
        title="Parser crash on null input",
        body="The parser crashes when input is null",
        existing_issues=existing_issues,
    )

    assert result.score > 0.5
