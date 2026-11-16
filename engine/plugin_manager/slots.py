# engine/plugin_manager/slots.py
"""前端扩展槽 —— 核心声明"哪里有口子",插件只能往里放,不能自己开洞。

槽位是一份核心持有的清单:页面决定在哪些位置渲染,插件在清单里声明放哪个槽。
插件写了一个不存在的槽,在加载期就被拒——否则它看起来装上了,卡片却永远不出现,
排查这件事比重装一遍还费劲。

`global.dock` 是"右下角那块悬浮区":核心只声明"这里能挂一样东西",具体挂什么
由插件决定。助手窗口不再是布局文件里写死的一个组件,而是这个槽上的一个消费者。
"""

from __future__ import annotations

SLOTS: dict[str, str] = {
    "issue-board.bento": "首页议题板的卡片列",
    "issue-detail.sidebar": "单个议题详情页右栏",
    "settings.plugins": "设置页底部",
    # 全局悬浮区:同一时刻只渲染一张卡片,由插件清单声明
    "global.dock": "右下角悬浮区(助手这类常驻窗口)",
}

# 同一时刻只能挂一张卡片的槽。两个插件抢同一个位置,页面上会叠成一团,
# 而且看起来像"样式坏了"而不是"配置错了",所以在加载期就判掉。
SINGLE_OCCUPANCY = frozenset({"global.dock"})


def known_slot(name: str) -> bool:
    return name in SLOTS


def single_occupancy(name: str) -> bool:
    return name in SINGLE_OCCUPANCY


def slot_hint() -> str:
    """给错误信息用的槽位清单,按名字排序。"""
    return "、".join(sorted(SLOTS))


__all__ = ["SLOTS", "SINGLE_OCCUPANCY", "known_slot", "single_occupancy", "slot_hint"]
