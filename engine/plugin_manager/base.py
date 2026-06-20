# engine/plugin_manager/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class PluginType(str, Enum):
    """插件类型"""
    ADAPTER = "adapter"
    AGENT = "agent"
    ACTION = "action"
    DASHBOARD_COMPONENT = "dashboard_component"


@dataclass
class PluginInfo:
    """插件信息"""
    name: str
    version: str
    type: PluginType
    description: str
    triggers: List[Dict[str, Any]] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)


class PluginBase(ABC):
    """插件基类，所有插件必须实现此接口"""

    @abstractmethod
    def info(self) -> PluginInfo:
        """返回插件信息"""
        pass

    @abstractmethod
    async def on_startup(self):
        """启动时初始化"""
        pass

    @abstractmethod
    async def on_shutdown(self):
        """关闭时释放资源"""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """健康检查"""
        pass

    @abstractmethod
    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理事件（事件触发）"""
        pass

    @abstractmethod
    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行任务（调度智能体触发）"""
        pass
