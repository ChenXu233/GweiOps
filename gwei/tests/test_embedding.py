# tests/test_embedding.py
import pytest
from unittest.mock import AsyncMock, patch
from src.services.embedding import EmbeddingService, SearchResult


@pytest.mark.asyncio
async def test_embed_text():
    service = EmbeddingService(api_key="test_key")

    with patch.object(service, "_call_embedding_api", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = [0.1] * 1536

        result = await service.embed_text("Hello, world!")

        assert len(result) == 1536
        assert result[0] == 0.1


@pytest.mark.asyncio
async def test_embed_texts():
    service = EmbeddingService(api_key="test_key")

    with patch.object(service, "_call_embedding_api", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = [[0.1] * 1536, [0.2] * 1536]

        result = await service.embed_texts(["Hello", "World"])

        assert len(result) == 2
        assert len(result[0]) == 1536


def test_cosine_similarity():
    service = EmbeddingService(api_key="test_key")

    vec_a = [1.0, 0.0, 0.0]
    vec_b = [0.0, 1.0, 0.0]
    vec_c = [1.0, 0.0, 0.0]

    assert service.cosine_similarity(vec_a, vec_b) == pytest.approx(0.0)
    assert service.cosine_similarity(vec_a, vec_c) == pytest.approx(1.0)


def test_search_result():
    result = SearchResult(id="1", score=0.95, content="test content")

    assert result.id == "1"
    assert result.score == 0.95
    assert result.content == "test content"
    assert result.metadata is None


@pytest.mark.asyncio
async def test_search():
    service = EmbeddingService(api_key="test_key")

    with patch.object(service, "embed_text", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = [1.0, 0.0, 0.0]

        vectors = [
            {"id": "1", "embedding": [1.0, 0.0, 0.0], "content": "exact match"},
            {"id": "2", "embedding": [0.0, 1.0, 0.0], "content": "orthogonal"},
            {"id": "3", "embedding": [0.5, 0.5, 0.0], "content": "partial match"},
        ]

        results = await service.search("test query", vectors, top_k=2)

        assert len(results) == 2
        assert results[0].id == "1"
        assert results[0].score == pytest.approx(1.0)
        assert results[0].content == "exact match"
        assert results[1].id == "3"
        assert results[1].score == pytest.approx(0.7071, rel=1e-3)


def test_cosine_similarity_zero_vector():
    service = EmbeddingService(api_key="test_key")

    vec_a = [1.0, 0.0, 0.0]
    vec_zero = [0.0, 0.0, 0.0]

    assert service.cosine_similarity(vec_a, vec_zero) == pytest.approx(0.0)


def test_cosine_similarity_dimension_mismatch():
    service = EmbeddingService(api_key="test_key")

    vec_a = [1.0, 0.0]
    vec_b = [1.0, 0.0, 0.0]

    with pytest.raises(ValueError, match="向量维度必须相同"):
        service.cosine_similarity(vec_a, vec_b)