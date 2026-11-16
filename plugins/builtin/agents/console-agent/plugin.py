# plugins/builtin/agents/console-agent/plugin.py
"""控制台助手的循环 —— 一个插件,不是一个硬编码在布局里的组件。

这个插件提供两样东西:

1. **能力 `console.chat`**:给定一个会话(权限、工具白名单、租户、目标都在里面),
   造一个能跑多步的 agent。闸门不在这里:改世界的调用走 `run_tool`,会话与审计
   归核心,`MAX_ACTIONS` 是核心数出来的。
2. **UI 槽 `global.dock`**:右下角那块浮窗。关掉它,浮窗就不渲染了——
   不是"渲染一个空的窗口",是不存在。

循环本身用 bub(`bub.core.Agent`)。没有 bub 或没有模型密钥时,`build` 抛
`AgentUnavailable`,控制台把原因说出来——不塞一个假的实现。
"""

from __future__ import annotations

from typing import Any

from engine.plugin_manager.base import PluginBase

from .loop import build_agent, missing_key

CAPABILITY = "console.chat"


class ConsoleAgent(PluginBase):
    """把 bub 的循环接上本机模型配置。"""

    name = "console-agent"

    async def on_startup(self) -> None:
        return None

    async def on_shutdown(self) -> None:
        return None

    async def health_check(self) -> bool:
        # 没有密钥时它仍然是"活着"的:能回答、能列工具,只是跑不了补全。
        # 健康检查回答"进程在不在",不回答"配置齐不齐"。
        return True

    async def handle_event(self, event: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"status": "ignored"}

    async def execute_task(
        self, task: str, params: dict[str, Any], ctx: Any = None
    ) -> dict[str, Any]:
        """能力通道的一次调用。`params` 里带会话与注册表。

        走能力通道的调用方(目前只有测试与诊断)拿不到"一个可 run 的对象"这种
        东西,所以这里只回答"能不能开工、缺什么"。
        """
        if task != "chat":
            return {"status": "unknown-task", "task": task}
        return {
            "status": "key-missing" if missing_key() else "ready",
            "capability": CAPABILITY,
        }

    def build(self, *, session: Any, registry: Any, actor: Any = None) -> Any:
        """给核心用的另一半:按会话造一个 agent。"""
        return build_agent(session=session, registry=registry, actor=actor)


__all__ = ["ConsoleAgent", "CAPABILITY"]
