# engine/workflows/scan.py
"""周期巡检:到点跑一次清单声明的能力,把差异交回事故管线。

调度只负责"到点"(见 [engine/scheduler](../scheduler/__init__.py)),这里负责
"跑"和"交出去"。分成两处的理由:调度要由 DBOS 管,而这里能脱离 DBOS 单测。

一次巡检就是一个信号,和告警、issue 走同一条链路——它不自带动作。巡检发现
"某个依赖过期"之后要不要动、动哪里,仍然由 intent 提供者提、平台判。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from dbos import DBOS

from engine.ingest.signal import normalize
from engine.plugin_manager import registry
from engine.workflows.pipeline import alert_triage_workflow

logger = logging.getLogger(__name__)

# 巡检产出的信号自带这个来源:它不是 GitHub,也不是某条告警。
SCAN_SOURCE = "scan"


def signal_from_scan(raw: Any, *, capability: str) -> dict[str, Any] | None:
    """巡检结果 → 信号。

    空结果是"这次没查出什么",不是事故:写一条什么都没有的事故,等于教人
    忽略事故列表。形状不对则相反——那是插件违约,当场抛出来,记成失败的巡检。
    """
    if raw is None or raw == {}:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"巡检 {capability} 返回了 {type(raw).__name__},不是一次检查结果")

    subject = str(raw.get("subject") or "").strip()
    title = str(raw.get("title") or "").strip()
    if not subject or not title:
        raise ValueError(f"巡检 {capability} 的结果缺少 subject 或 title")

    extra = {
        key: value
        for key, value in raw.items()
        if key not in ("subject", "title", "detail", "severity", "ref")
    }
    extra["capability"] = capability

    return normalize(
        source=SCAN_SOURCE,
        subject=subject,
        title=title,
        detail=str(raw.get("detail") or ""),
        severity=str(raw.get("severity") or "medium"),
        ref=str(raw.get("ref") or ""),
        extra=extra,
    )


async def _run_scan_impl(context: dict) -> dict[str, Any] | None:
    """跑一次巡检。没有提供者、提供者报错都照原样抛出:那是配置坏了,不是"没事"。"""
    capability = str(context.get("capability") or "")
    if not capability:
        raise ValueError("巡检载荷缺少 capability")

    raw = await registry.run_capability(
        capability,
        {
            "schedule": context.get("schedule_name", ""),
            "tenant": context.get("tenant_slug", ""),
        },
        tenant=context.get("tenant_slug", ""),
    )
    return signal_from_scan(raw, capability=capability)


@DBOS.step()
async def scan_step(context: dict) -> dict[str, Any] | None:
    return await _run_scan_impl(context)


@DBOS.workflow()
async def scheduled_scan_workflow(scheduled_at: datetime, context: dict) -> dict:
    """DBOS 到点调用:先跑巡检,真查出东西才开事故。

    事故管线按子工作流调用,不另起一条队列:一次巡检本来就只产出一条信号,
    没有"多租户抢配额"的问题;而把它搬到别的队列上,等于让这条链路绕开
    告警那条链路的口径。
    """
    ctx = dict(context or {})
    found = await scan_step(ctx)
    if not found:
        logger.info("巡检 %s:这次没查出什么", ctx.get("capability", ""))
        return {"status": "empty", "capability": ctx.get("capability", "")}

    report = await alert_triage_workflow(
        {"tenant_slug": ctx.get("tenant_slug", ""), "signal": found}
    )
    return {
        "status": "reported",
        "capability": ctx.get("capability", ""),
        "signal": found.get("subject", ""),
        "report": report,
    }
