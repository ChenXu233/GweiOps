# plugins/builtin/agents/selfcheck/plugin.py
"""平台自检:只报告,不修自己。

一次检查的结果要么是 None(这次没查出什么),要么是一条
{subject, title, detail, severity, ref}——后者由 scan 包成信号,走和告警一样的事故管线。

为什么不自修:自检发现自己坏了就自动改自己,是坏循环。改坏了下次自检跟着坏,
没人能踩刹车。所以这里只报,修复永远由人点。

为什么只查这两件:插件健康在部署那一刻就该由人看(未配置的适配器也会报 False,
那不是"坏了"),事故堆积需要业务库而插件拿不到。剩下两件是它真看得见、且一定是
问题的事:工作区写满、工作流排队排到失控。
"""

from __future__ import annotations

import logging
import shutil
from typing import Any, Dict

from dbos import DBOS
from engine.plugin_manager.base import PluginBase

logger = logging.getLogger(__name__)

WORKSPACE = "/workspaces"
DISK_FREE_WARN = 0.10  # 工作区剩余不足 10%
QUEUE_WARN = 100       # 排队中的工作流超过这个数
SUBJECT = "gwei-engine"


def disk_finding() -> dict[str, Any] | None:
    """工作区余量。没有这个目录(不在容器里跑)就不算这项。"""
    try:
        usage = shutil.disk_usage(WORKSPACE)
    except OSError:
        return None
    if not usage.total or usage.free / usage.total >= DISK_FREE_WARN:
        return None
    return {
        "subject": SUBJECT,
        "title": "工作区快满了",
        "detail": (
            f"{WORKSPACE} 只剩 {usage.free / 1e9:.1f} GB / {usage.total / 1e9:.1f} GB"
            f"({usage.free / usage.total:.0%});新的事故会写不进工作区"
        ),
        "severity": "high",
        "ref": "selfcheck:disk",
    }


async def queue_finding() -> dict[str, Any] | None:
    """工作流队列积压。读不到就当没有这一项——自检不该因为子系统没起来而报假警。"""
    from engine.workflows.pipeline import WORKFLOW_QUEUE

    try:
        queued = await DBOS.list_queued_workflows_async(
            queue_name=WORKFLOW_QUEUE, limit=QUEUE_WARN + 1
        )
    except Exception:  # noqa: BLE001 - DBOS 没起来/版本不认参数,都不是"出事了"
        logger.info("自检读不到队列长度,跳过这一项", exc_info=True)
        return None
    if len(queued) <= QUEUE_WARN:
        return None
    return {
        "subject": SUBJECT,
        "title": "工作流队列积压",
        "detail": f"{WORKFLOW_QUEUE} 里排队超过 {QUEUE_WARN} 个,worker 可能卡住了",
        "severity": "medium",
        "ref": "selfcheck:queue",
    }


async def run_self_check() -> dict[str, Any] | None:
    """查一遍。第一个问题就是这次的结论:一条巡检只产出一条信号。"""
    return disk_finding() or await queue_finding()


class SelfCheckAgent(PluginBase):
    """把自检挂成一个能力,由清单里的 schedule 到点触发。"""

    async def on_startup(self) -> None:
        return None

    async def on_shutdown(self) -> None:
        return None

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "ignored"}

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Any:
        if task != "self_check":
            # 形状不对是插件违约,当场抛:scan 会把它记成失败的巡检,而不是"没事"
            raise ValueError(f"SelfCheckAgent 不认识的任务: {task}")
        return await run_self_check()
