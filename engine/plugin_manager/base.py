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
    """插件基类。

    **没有 `info()`**:插件是什么由清单(`plugin.yaml`)唯一声明,核心在加载期
    就校验过。再让插件用代码回答一遍"我叫什么、我有什么能力",等于把同一个事实
    存两份——两份会漂移,而漂移的那份在页面上看不出是错的。这里只留"做事"的
    那几个方法。
    """

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
