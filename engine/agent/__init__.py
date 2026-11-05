# engine/agent/__init__.py
"""出口:沙箱里的 agent 改变外部世界的唯一通道。"""

from .tools import ToolCall, ToolResult, is_mutating, run_tool, tool_specs

__all__ = ["ToolCall", "ToolResult", "tool_specs", "run_tool", "is_mutating"]
