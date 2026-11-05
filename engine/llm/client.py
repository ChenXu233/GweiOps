# engine/llm/client.py
import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any
from engine.shared.config import config
from engine.shared.metrics import metrics

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


@dataclass
class ToolChatResult:
    """一次带工具的对话。tool_calls 为空就是"它不想调东西了"。"""

    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens_used: int = 0
    model: str = ""


class LLMService:
    """LLM 调用封装。支持重试和指数退避。"""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        settings = config.settings
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model
        self.provider = settings.llm_provider
        self.api_base = settings.llm_base_url or None

        # 是否启用真实调用
        self.enabled = HAS_LITELLM and bool(self.api_key)

    async def call(
        self,
        system_prompt: str,
        user_prompt: str,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> LLMCallResult:
        """调用 LLM，带重试和指数退避；调用耗时/次数计入指标(计费计量源)。"""
        last_error = None
        for attempt in range(max_retries):
            try:
                start = time.monotonic()
                result = await self._call_api(system_prompt, user_prompt)
                metrics.observe(
                    "gwei_llm_call_duration_seconds",
                    time.monotonic() - start,
                    {"model": self.model},
                )
                metrics.increment("gwei_llm_calls_total", {"model": self.model})
                metrics.increment(
                    "gwei_llm_tokens_total",
                    {"model": self.model},
                    amount=result.tokens_used,
                )
                return result
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    await asyncio.sleep(delay)

        raise last_error or Exception("LLM call failed after max retries")

    async def call_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> ToolChatResult:
        """带工具的一次对话。工具结果怎么回填由调用方决定。

        没有模型时返回空 tool_calls:调用方看到"它没想调东西"就自然收尾,
        不必在每个插件里再写一条"没有模型"的分支。
        """
        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                return await self._call_tools(messages, tools)
            except Exception as e:  # noqa: BLE001 - 重试完再抛,口径与 call 一致
                last_error = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(base_delay * (2**attempt))
        raise last_error or Exception("LLM call failed after max retries")

    async def _call_tools(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ToolChatResult:
        if not self.enabled:
            return ToolChatResult(
                content="(没有配置模型,这次没有可执行的动作)",
                tokens_used=0,
                model=self.model,
            )

        start = time.monotonic()
        response = await acompletion(
            model=self._build_model_string(),
            messages=messages,
            tools=tools or None,
            temperature=0.2,
            api_key=self.api_key,
            api_base=self.api_base,
        )
        metrics.observe(
            "gwei_llm_call_duration_seconds",
            time.monotonic() - start,
            {"model": self.model},
        )
        metrics.increment("gwei_llm_calls_total", {"model": self.model})

        message = response.choices[0].message
        calls: list[dict[str, Any]] = []
        for call in getattr(message, "tool_calls", None) or []:
            raw = getattr(call.function, "arguments", "") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except ValueError:
                args = {}
            calls.append(
                {
                    "id": getattr(call, "id", ""),
                    "name": getattr(call.function, "name", ""),
                    "args": args if isinstance(args, dict) else {},
                }
            )

        tokens = response.usage.total_tokens if response.usage else 0
        metrics.increment("gwei_llm_tokens_total", {"model": self.model}, amount=tokens)

        return ToolChatResult(
            content=message.content or "",
            tool_calls=calls,
            tokens_used=tokens,
            model=self.model,
        )

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
        # 自定义 OpenAI 兼容端点：litellm 要求 openai/ 前缀 + api_base
        if self.api_base and not prefix:
            prefix = "openai/"
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
            api_base=self.api_base,
        )

        content = response.choices[0].message.content or ""
        tokens_used = response.usage.total_tokens if response.usage else 0

        return LLMCallResult(
            content=content,
            tokens_used=tokens_used,
            model=self.model,
        )
