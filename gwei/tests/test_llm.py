# tests/test_llm.py
import pytest
from unittest.mock import AsyncMock, patch
from src.services.llm import LLMService, LLMCallResult


@pytest.mark.asyncio
async def test_llm_call_success():
    service = LLMService(api_key="test_key", model="test-model")

    with patch.object(service, "_call_api", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = LLMCallResult(
            content="Hello, world!",
            tokens_used=42,
            model="test-model",
        )

        result = await service.call(
            system_prompt="You are helpful.",
            user_prompt="Say hello",
        )

        assert result.content == "Hello, world!"
        assert result.tokens_used == 42


@pytest.mark.asyncio
async def test_llm_call_retry_on_failure():
    service = LLMService(api_key="test_key", model="test-model")

    with patch.object(service, "_call_api", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = [
            Exception("API error"),
            Exception("API error"),
            LLMCallResult(content="Success after retry", tokens_used=10, model="test-model"),
        ]

        result = await service.call(
            system_prompt="Test",
            user_prompt="Test",
            max_retries=3,
        )

        assert result.content == "Success after retry"
        assert mock_call.call_count == 3


@pytest.mark.asyncio
async def test_llm_call_max_retries_exceeded():
    service = LLMService(api_key="test_key", model="test-model")

    with patch.object(service, "_call_api", new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = Exception("API error")

        try:
            await service.call(
                system_prompt="Test",
                user_prompt="Test",
                max_retries=2,
            )
            assert False, "Expected exception"
        except Exception as e:
            assert "API error" in str(e)
            assert mock_call.call_count == 2
