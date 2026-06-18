# src/services/llm.py
import asyncio
from dataclasses import dataclass
from src.config import Settings


@dataclass
class LLMCallResult:
    content: str
    tokens_used: int
    model: str


class LLMService:
    """LLM 调用封装。支持重试和指数退避。"""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = Settings()
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model
        self.provider = settings.llm_provider

    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> LLMCallResult:
        """调用 LLM，带重试和指数退避。"""
        last_error = None
        for attempt in range(max_retries):
            try:
                return await self._call_api(system_prompt, user_prompt)
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    await asyncio.sleep(delay)

        raise last_error or Exception("LLM call failed after max retries")

    async def _call_api(self, system_prompt: str, user_prompt: str) -> LLMCallResult:
        """实际调用 LLM API。简化版：返回模拟结果。"""
        return LLMCallResult(
            content=f"Response to: {user_prompt[:50]}...",
            tokens_used=len(user_prompt) // 4,
            model=self.model,
        )
