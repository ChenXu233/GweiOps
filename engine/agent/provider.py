# engine/agent/provider.py
"""助手循环的接缝 —— 平台问注册表要一个 agent,自己不留实现。

控制台助手的**闸门**留在核心(会话、权限、待批、`MAX_ACTIONS`、审计、出口),
**循环**是可换的:模型调用、提示词、多步预算这些都归提供者。

这个文件只定义那张契约,不实现它。默认实现是内置插件 `console-agent`
(`capabilities: [console.chat]`);关掉它,控制台如实回答"没有提供者",
而不是悄悄塞一个内置循环进来——那会和"关掉插件等于关掉这个功能"这件事矛盾。

契约刻意窄:`build(session, registry, actor)` 返回一个对象,那个对象有一个
`run(message, tape=...)` 的异步上下文管理器,产出的流里每一条事件都有
`kind` 与 `data`。字段名与 bub 的事件同形,因为默认实现就是 bub;
换实现只要照这个形状说话,平台不关心它背后是谁。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

CAPABILITY = "console.chat"

# 事件 kind。平台只认这五种,提供者多说无益——多出来的会被忽略。
EVENT_KINDS = ("text", "tool_call", "tool_result", "usage", "error")


@runtime_checkable
class AgentProvider(Protocol):
    """一个能在控制台会话里跑多步循环的东西。"""

    def build(self, *, session: Any, registry: Any, actor: Any = None) -> Any:
        """按会话构造一份 agent;每次对话都要现构造(工具清单按当下权限算)。"""


class AgentUnavailable(LookupError):
    """没有提供者,或者提供者起不来。调用方如实回报,不塞默认实现。"""


def build_agent(*, session: Any, registry: Any, actor: Any = None) -> Any:
    """向注册表要一个 agent。

    找不到提供者就抛 `AgentUnavailable`,并把"该开哪个插件"写进错误信息。
    这不是防御性代码:控制台助手浮窗本身就挂在一个插件上,插件关掉之后
    这条路径仍然可能被直接调用(比如前端缓存了会话),那时要说得清为什么没有。
    """
    provider = registry.best_capability_provider(CAPABILITY)
    if provider is None:
        raise AgentUnavailable(
            f"没有 agent 提供者:控制台助手由插件提供(能力 {CAPABILITY}),"
            "请启用 console-agent 插件"
        )
    builder = getattr(provider, "build", None)
    if builder is None:
        raise AgentUnavailable(
            f"{type(provider).__name__} 声明了 {CAPABILITY},但没有实现 build(session=...)"
        )
    return builder(session=session, registry=registry, actor=actor)


__all__ = ["AgentProvider", "AgentUnavailable", "CAPABILITY", "EVENT_KINDS", "build_agent"]
