# engine/scheduler/__init__.py
"""周期巡检的接线 —— 清单声明周期,调度交给 DBOS,这里只做换算与交接。

不自建循环:DBOS 的调度器已经把"同一周期只跑一次"做进了系统库
(工作流 id = `sched-<调度名>-<点火时刻>`),重启后重复点火会被它挡掉。
自己拿 asyncio 写一个循环,要重新回答的正是这个问题,而答案只能靠一个
别人已经在维护的东西。

对账也在这里:声明了没装上的要说出来,清单里删掉的周期要跟着删掉——
一个已经没人声明的巡检还在每六小时跑一次,是比没跑更难查的事。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# 平台自己建的周期用这个前缀,对账时只碰自己建的,不动别人往库里塞的东西。
SCHEDULE_PREFIX = "plugin-scan-"


def schedule_name(plugin: str, capability: str) -> str:
    """一条周期在调度器里的名字。带插件名:两个插件可以声明同一个能力。"""
    return f"{SCHEDULE_PREFIX}{plugin}-{capability}"


def every_to_cron(seconds: int) -> str:
    """秒数 → 6 段 cron(秒 分 时 日 月 周)。只在清单校验放行过的周期上调用。"""
    if seconds < 60:
        return f"*/{seconds} * * * * *"
    if seconds < 3600:
        return f"0 */{seconds // 60} * * * *"
    if seconds < 86400:
        return f"0 0 */{seconds // 3600} * * *"
    return "0 0 0 * * *"


def schedule_inputs(
    registry_obj: Any, *, tenant: str = ""
) -> list[dict[str, Any]]:
    """清单里声明的周期 → `DBOS.apply_schedules` 的入参。"""
    from engine.workflows.scan import scheduled_scan_workflow

    entries: list[dict[str, Any]] = []
    for manifest in registry_obj.manifests():
        for decl in manifest.schedules:
            entries.append(
                {
                    "schedule_name": schedule_name(manifest.name, decl.capability),
                    "workflow_fn": scheduled_scan_workflow,
                    "schedule": every_to_cron(decl.every_s),
                    "context": {
                        "tenant_slug": tenant,
                        "capability": decl.capability,
                        "plugin": manifest.name,
                        "schedule_name": schedule_name(manifest.name, decl.capability),
                        "every_s": decl.every_s,
                    },
                }
            )
    return entries


def _default_apply(entries: list[dict[str, Any]]) -> None:
    from dbos import DBOS

    DBOS.apply_schedules(entries)


def _default_list() -> list[dict[str, Any]]:
    from dbos import DBOS

    return DBOS.list_schedules(schedule_name_prefix=SCHEDULE_PREFIX)


def _default_delete(name: str) -> None:
    from dbos import DBOS

    DBOS.delete_schedule(name)


def apply_registry_schedules(
    registry_obj: Any,
    *,
    tenant: str = "",
    apply: Callable[[list[dict[str, Any]]], None] | None = None,
    list_schedules: Callable[[], list[dict[str, Any]]] | None = None,
    delete: Callable[[str], None] | None = None,
) -> dict[str, list]:
    """把清单里的周期装进调度器,并删掉已经没人声明的那些。

    一条一条装,不用批量:`apply_schedules` 是原子的,一条写坏会把整批都挡掉。
    一个坏周期不该让其余巡检一起停摆。

    返回 `{"applied": [...], "failed": [{"schedule", "error"}], "removed": [...]}`,
    由调用方决定怎么说出来——这里不吞异常,也不假装装上了。
    """
    apply_ = apply or _default_apply
    list_ = list_schedules or _default_list
    delete_ = delete or _default_delete

    entries = schedule_inputs(registry_obj, tenant=tenant)

    applied: list[str] = []
    failed: list[dict[str, str]] = []
    for entry in entries:
        name = entry["schedule_name"]
        try:
            apply_([entry])
        except Exception as exc:  # noqa: BLE001 - 单条失败要说出来,不拖累其余
            failed.append({"schedule": name, "error": f"{type(exc).__name__}: {exc}"})
            logger.warning("巡检周期没装上 %s: %s", name, exc)
            continue
        applied.append(name)

    removed: list[str] = []
    declared = {entry["schedule_name"] for entry in entries}
    try:
        existing = list_()
    except Exception as exc:  # noqa: BLE001 - 对账读不到就只报告,不因此不装
        logger.warning("读不到已有周期,这次不做清理: %s", exc)
        existing = []
    for schedule in existing:
        name = str(schedule.get("schedule_name") or "")
        # 只碰自己建的:库里可能还有别人(或别的版本)留下的周期。
        if not name.startswith(SCHEDULE_PREFIX) or name in declared:
            continue
        try:
            delete_(name)
            removed.append(name)
        except Exception as exc:  # noqa: BLE001 - 删不掉要说出来
            failed.append({"schedule": name, "error": f"{type(exc).__name__}: {exc}"})
            logger.warning("清理旧周期失败 %s: %s", name, exc)

    return {"applied": applied, "failed": failed, "removed": removed}
