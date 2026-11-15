# engine/plugin_manager/slots.py
"""前端扩展槽 —— 核心声明"哪里有口子",插件只能往里放,不能自己开洞。

槽位是一份核心持有的清单:页面决定在哪些位置渲染,插件在清单里声明放哪个槽。
插件写了一个不存在的槽,在加载期就被拒——否则它看起来装上了,卡片却永远不出现,
排查这件事比重装一遍还费劲。
"""

from __future__ import annotations

SLOTS: dict[str, str] = {
    "issue-board.bento": "首页议题板的卡片列",
    "issue-detail.sidebar": "单个议题详情页右栏",
    "settings.plugins": "设置页底部",
}


def known_slot(name: str) -> bool:
    return name in SLOTS


def slot_hint() -> str:
    """给错误信息用的槽位清单,按名字排序。"""
    return "、".join(sorted(SLOTS))


__all__ = ["SLOTS", "known_slot", "slot_hint"]
