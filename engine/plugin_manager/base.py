# engine/plugin_manager/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any
from enum import Enum


class PluginType(str, Enum):
    """插件类型"""
    ADAPTER = "adapter"
    AGENT = "agent"
    ACTION = "action"
    DASHBOARD_COMPONENT = "dashboard_component"


class PluginBase(ABC):
    """插件基类。插件是什么由清单(`plugin.yaml`)唯一声明,这里只留做事的方法。"""

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

    async def handle_hook(self, point: str, payload: Dict[str, Any]) -> Any:
        """Hook 订阅处理器（默认恒等返回，插件按清单声明的 mode 自行约定返回值）"""
        return payload
