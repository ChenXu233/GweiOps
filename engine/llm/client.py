# engine/llm/client.py
import asyncio
from dataclasses import dataclass
from engine.shared.config import Settings

try:
    from openai import AsyncOpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


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

        # 初始化 OpenAI 客户端
        if HAS_OPENAI and self.api_key:
            self.client = AsyncOpenAI(api_key=self.api_key)
        else:
            self.client = None

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
        """实际调用 LLM API。"""
        if not self.client:
            # 模拟模式（用于测试）
            return LLMCallResult(
                content=f"Response to: {user_prompt[:50]}...",
                tokens_used=len(user_prompt) // 4,
                model=self.model,
            )

        # 真实调用 OpenAI API
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
        )

        content = response.choices[0].message.content or ""
        tokens_used = response.usage.total_tokens if response.usage else 0

        return LLMCallResult(
            content=content,
            tokens_used=tokens_used,
            model=self.model,
        )
