# engine/agent/loop.py
"""bub 的循环,接到这台机器的模型配置上。

bub 自己认模型(`BubModel` + `republic` 的 provider),所以这里不再翻译消息、不再
摊平补全:一轮对话的推、执行、再看结果整段是 bub 的,模型也由它开流。

这台机器只交代三件事:用哪个 `provider:model`、凭据从哪来、不可用时说哪句。
工具与权限全在 `engine/agent/console.py`,这里不碰。
"""

from __future__ import annotations

from typing import Any

from engine.shared.config import config

try:  # bub 是控制台助手的 loop;没装时这一条 import 失败,由路由报一条错误
    from bub.builtin.model import BubModel
    from bub.core import Agent
    from bub.core.tools import model_tools

    HAS_BUB = True
except ImportError:  # pragma: no cover - 只在没装 bub 的部署里走到
    BubModel = None  # type: ignore[assignment]
    Agent = None  # type: ignore[assignment]
    HAS_BUB = False

# litellm 那套的 provider 名与 republic 认的名字不总一样。这里只列对不上的那些;
# 其余(openai / anthropic / deepseek / google / ollama / mistral / groq …)同名。
_PROVIDER_ALIASES = {
    "gemini": "google",
    "vertex_ai": "google",
    "azure_openai": "azure",
    "zhipu": "zai",
}

# 报错用词:模型这一侧没配好时,结论要能被搜索到,不要拟人。
NOT_CONFIGURED = (
    "模型不可用:未配置 LLM_API_KEY。控制台助手无法发起补全,工具清单与权限判据不受影响。"
)
NOT_INSTALLED = "模型不可用:bub 未安装(缺少依赖 bub>=0.6.1),控制台助手无法启动。"


def model_spec(model: str = "", provider: str = "") -> str:
    """`provider:model`。模型串里已经带了 provider 就以它为准(如 `openai/vllm`)。"""
    name = (model or config.settings.llm_model or "").strip()
    if "/" in name and not name.startswith("/"):
        head, _, tail = name.partition("/")
        return f"{_provider(head)}:{tail}"
    return f"{_provider(provider or config.settings.llm_provider)}:{name}"


def client_options(spec: str) -> dict[str, Any]:
    """这个 provider 的凭据与端点。bub 把它们交给 `republic.get_model`。"""
    _, _, name = spec.partition(":")
    options: dict[str, Any] = {"api_key": config.settings.llm_api_key or None, "model": name}
    base_url = (config.settings.llm_base_url or "").strip()
    if base_url:
        options["base_url"] = base_url
    return options


def _provider(raw: str) -> str:
    name = (raw or "openai").strip().lower()
    return _PROVIDER_ALIASES.get(name, name)


def missing_key() -> bool:
    return not (config.settings.llm_api_key or "").strip()


def session_agent(*, session: Any, registry: Any, actor: Any = None):
    """一个会话用的 bub agent。

    子类只改写一件事:**每次运行都把会话当下的工具清单交给模型**。清单按
    `actor` 此刻的权限算(session 只是上限),所以权限被改窄、被收回,下一步
    就看不见那些工具了 —— 工具清单不是构造时定死的。
    """
    if not HAS_BUB:  # pragma: no cover - 只在没装 bub 的部署里走到
        raise RuntimeError(NOT_INSTALLED)

    from engine.agent.console import MAX_STEPS, SYSTEM_PROMPT, bub_tools

    spec = model_spec()
    model = BubModel(spec, client_options=lambda _provider: client_options(spec))

    class SessionAgent(Agent):
        """按会话现算工具,其余照 bub 的规矩来。"""

        async def prepare_tools(self, tape: Any, prompt: Any) -> list[Any]:
            return model_tools(bub_tools(session, registry, actor))

    return SessionAgent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        max_steps=MAX_STEPS,
        name="gweiops-console",
    )


__all__ = [
    "HAS_BUB",
    "NOT_CONFIGURED",
    "NOT_INSTALLED",
    "client_options",
    "missing_key",
    "model_spec",
    "session_agent",
]
