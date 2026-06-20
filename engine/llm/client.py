# engine/llm/client.py
import asyncio
from dataclasses import dataclass
from engine.shared.config import Settings

try:
    from litellm import acompletion
    HAS_LITELLM = True
except ImportError:
    HAS_LITELLM = False


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

        # 是否启用真实调用
        self.enabled = HAS_LITELLM and bool(self.api_key)

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

    def _build_model_string(self) -> str:
        """根据 provider 构建 litellm 模型字符串。"""
        if "/" in self.model:
            return self.model
        provider_prefixes = {
            "openai": "openai/",
            "anthropic": "anthropic/",
            "azure": "azure/",
            "gemini": "gemini/",
            "deepseek": "deepseek/",
        }
        prefix = provider_prefixes.get(self.provider, "")
        return f"{prefix}{self.model}"

    async def _call_api(self, system_prompt: str, user_prompt: str) -> LLMCallResult:
        """实际调用 LLM API（通过 litellm）。"""
        if not self.enabled:
            # 模拟模式（用于测试）
            return LLMCallResult(
                content=f"Response to: {user_prompt[:50]}...",
                tokens_used=len(user_prompt) // 4,
                model=self.model,
            )

        # 通过 litellm 调用 LLM API
        model_string = self._build_model_string()
        response = await acompletion(
            model=model_string,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            api_key=self.api_key,
        )

        content = response.choices[0].message.content or ""
        tokens_used = response.usage.total_tokens if response.usage else 0

        return LLMCallResult(
            content=content,
            tokens_used=tokens_used,
            model=self.model,
        )
