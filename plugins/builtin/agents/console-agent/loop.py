# plugins/builtin/agents/console-agent/loop.py
"""bub 的循环接上本机模型配置 —— 现在住在插件里。

bub 自带模型入口(`BubModel` + provider),这里不做消息翻译与补全摊平。
本模块只提供三样:`provider:model` 规格、凭据来源、不可用时的报错。
工具与权限不在这里:核心把 `bub_tools(session, registry, actor)` 递进来,
插件只负责"每次运行现算工具清单",保证权限收窄后下一步即生效。
"""

from __future__ import annotations

from typing import Any

from engine.shared.config import config

try:  # 未装 bub 时此 import 失败,由调用方报错
    from bub.builtin.model import BubModel
    from bub.core import Agent
    from bub.core.tools import model_tools

    HAS_BUB = True
except ImportError:  # pragma: no cover - 只在没装 bub 的部署里走到
    BubModel = None  # type: ignore[assignment]
    Agent = None  # type: ignore[assignment]
    HAS_BUB = False

# litellm 与 republic 的 provider 名不总一致;只列别名,其余同名。
_PROVIDER_ALIASES = {
    "gemini": "google",
    "vertex_ai": "google",
    "azure_openai": "azure",
    "zhipu": "zai",
}

# 报错文案要求可检索、不拟人。
NOT_CONFIGURED = (
    "模型不可用:未配置 LLM_API_KEY。控制台助手无法发起补全,工具清单与权限判据不受影响。"
)
NOT_INSTALLED = "模型不可用:bub 未安装(缺少依赖 bub>=0.6.1),控制台助手无法启动。"


def model_spec(model: str = "", provider: str = "") -> str:
    """`provider:model` 规格;模型串自带 provider 时以其为准(如 `openai/vllm`)。"""
    name = (model or config.settings.llm_model or "").strip()
    if "/" in name and not name.startswith("/"):
        head, _, tail = name.partition("/")
        return f"{_provider(head)}:{tail}"
    return f"{_provider(provider or config.settings.llm_provider)}:{name}"


def client_options(spec: str) -> dict[str, Any]:
    """该 provider 的凭据与端点,由 bub 交给 model 实现。"""
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


def build_agent(*, session: Any, registry: Any, actor: Any = None) -> Any:
    """按会话造一个 bub agent。

    仅重写 `prepare_tools`:每次运行按 `actor` 当前权限现算工具清单(session 只是
    上限),权限收窄后下一步即生效,工具清单不固定在构造时。

    没有 bub 时抛 `LookupError`,由调用方翻成人话——插件不替核心决定"要不要报错"。
    """
    if not HAS_BUB:  # pragma: no cover - 只在没装 bub 的部署里走到
        raise LookupError(NOT_INSTALLED)

    # 闸门那半边在核心:会话、权限、待批、动作上限都在 `engine.agent.console`
    from engine.agent.console import MAX_STEPS, SYSTEM_PROMPT, bub_tools

    spec = model_spec()
    model = BubModel(spec, client_options=lambda _provider: client_options(spec))

    class SessionAgent(Agent):
        """按会话现算工具,其余沿用 bub 默认行为。"""

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
    "build_agent",
    "client_options",
    "missing_key",
    "model_spec",
]
