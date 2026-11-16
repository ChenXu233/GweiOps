from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from enum import Enum

from .context import PluginContext


class PluginType(str, Enum):
    """插件类型"""
    ADAPTER = "adapter"
    AGENT = "agent"
    ACTION = "action"
    DASHBOARD_COMPONENT = "dashboard_component"


class PluginBase(ABC):
    """插件基类。插件是什么由清单(`plugin.yaml`)唯一声明,这里只留做事的方法。

    `execute_task` 的第三个参数 `ctx` 是这次调用的上下文(租户、目标、调用者、
    手上的数据级别)。它是**可选**的:老插件只实现两个位置参数,核心照样调得通。
    """

    # 插件自己声明的租户/目标;清单里也能声明,实例属性优先(见 registry)
    tenant: str = ""
    binding: str = ""

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
