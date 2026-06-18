# tests/test_llm_real.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.services.llm import LLMService, LLMCallResult


@pytest.mark.asyncio
async def test_llm_mock_mode():
    """测试无 API Key 时的模拟模式。"""
    service = LLMService(api_key="", model="test-model")

    result = await service.call(
        system_prompt="You are helpful.",
        user_prompt="Say hello",
    )

    assert "Response to" in result.content
    assert result.tokens_used > 0


@pytest.mark.asyncio
async def test_llm_with_mock_client():
    """测试带 Mock 客户端的调用。"""
    service = LLMService(api_key="test-key", model="test-model")

    # Mock OpenAI 客户端
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Hello!"))]
    mock_response.usage = MagicMock(total_tokens=42)

    service.client = AsyncMock()
    service.client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await service.call(
        system_prompt="You are helpful.",
        user_prompt="Say hello",
    )

    assert result.content == "Hello!"
    assert result.tokens_used == 42


@pytest.mark.asyncio
async def test_llm_retry_on_failure():
    """测试失败重试。"""
    service = LLMService(api_key="test-key", model="test-model")

    # Mock 客户端，前两次失败，第三次成功
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Success"))]
    mock_response.usage = MagicMock(total_tokens=10)

    service.client = AsyncMock()
    service.client.chat.completions.create = AsyncMock(
        side_effect=[
            Exception("API Error"),
            Exception("API Error"),
            mock_response,
        ]
    )

    result = await service.call(
        system_prompt="Test",
        user_prompt="Test",
        max_retries=3,
        base_delay=0.01,  # 快速重试
    )

    assert result.content == "Success"
    assert service.client.chat.completions.create.call_count == 3


@pytest.mark.asyncio
async def test_llm_max_retries_exceeded():
    """测试超过最大重试次数。"""
    service = LLMService(api_key="test-key", model="test-model")

    service.client = AsyncMock()
    service.client.chat.completions.create = AsyncMock(
        side_effect=Exception("API Error")
    )

    with pytest.raises(Exception, match="API Error"):
        await service.call(
            system_prompt="Test",
            user_prompt="Test",
            max_retries=2,
            base_delay=0.01,
        )

    assert service.client.chat.completions.create.call_count == 2
