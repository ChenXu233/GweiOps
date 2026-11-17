# engine/projects/onboarding.py
"""一个工作区走到"第一条工作流跑通"还差什么。

自助开通的门槛不是"有个注册按钮",是**陌生人不看文档、不找人问,也能知道下一步做什么**。
所以这里不去猜,只如实回答三件事,每件事都带一个"现在就能点的下一步":

| 步骤 | 什么算做到了 | 没做到时给人什么 |
| --- | --- | --- |
| 工作区 | 一定成立 —— 注册就建了一个 | — |
| 接入来源 | 至少有一个来源在跑(GitHub App 装上,或库里存了 CNB / GitLab 的令牌) | 去哪个页面、配哪个环境变量名 |
| 第一条工作流 | 账本里第一行,或议题板上第一条议题 | 先把仓库接进来,再去仓库上跑一次 |

**这里不写任何东西**。它是只读的:状态从来源配置、仓库数、议题与账本现算,
不落一张"开通进度"表 —— 那种表迟早和事实对不上,而"开通到哪一步了"恰恰是
最不该对不上的那种数据。
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from engine.db.models import ChangeEvent, Issue, Project

# 每个来源"接进来"看哪几项配置。名字就是插件清单里 `config` 声明的那些 ——
# 说"去配置来源"等于什么都没说,说 `GITLAB_TOKEN` 才能照着办。
# 同一份清单也用于读租户级覆盖(`config.get_scope_config(plugin_id, tenant)`)。
SOURCE_KEYS: dict[str, str] = {
    "github-app": "GITHUB_APP_APP_ID",
    "cnb-adapter": "CNB_WEBHOOK_TOKEN",
    "gitlab-adapter": "GITLAB_WEBHOOK_TOKEN",
}
SOURCE_LABELS: dict[str, str] = {
    "github-app": "GitHub",
    "cnb-adapter": "CNB",
    "gitlab-adapter": "GitLab",
}


def _configured_sources(tenant: str) -> set[str]:
    """这个工作区已经接通了哪些来源。

    两处都看:库里的租户级覆盖优先,其次部署这一层(环境变量)。判据是"那一项
    必填配置有值" —— 不空就已经能收投递了,再严就会把"用默认值就能跑"的部署
    判成没接。
    """
    from engine.shared.config import config as app_config

    out: set[str] = set()
    for plugin_id, key in SOURCE_KEYS.items():
        value = ""
        try:
            value = str(app_config.get_scope_config(plugin_id, tenant).get(key) or "")
        except Exception:  # noqa: BLE001 - 清单没登记这个 scope 时按"没配"算
            value = ""
        if not value:
            value = str(getattr(app_config.settings, key.lower(), "") or "")
        if value:
            out.add(plugin_id)
    return out


async def onboarding_status(
    session: AsyncSession, tenant_id: uuid.UUID, *, settings
) -> dict:
    """这个工作区离"第一条工作流"还差什么。只读。

    返回的每一项都带 `done` 与 `next`:`next` 是**人能做的那一步**,不是一句"未完成"。
    """
    repos = int(
        await session.scalar(
            select(func.count()).select_from(Project).where(
                Project.tenant_id == tenant_id, Project.parent_id.is_not(None)
            )
        )
        or 0
    )
    issues = int(
        await session.scalar(
            select(func.count())
            .select_from(Issue)
            .join(Project, Project.id == Issue.project_id)
            .where(Project.tenant_id == tenant_id)
        )
        or 0
    )
    # 账本按租户字符串存;工作区 slug 是它的用户名
    from engine.db.models import Tenant

    slug = await session.scalar(select(Tenant.slug).where(Tenant.id == tenant_id)) or ""
    changes = int(
        await session.scalar(
            select(func.count()).select_from(ChangeEvent).where(ChangeEvent.tenant == slug)
        )
        or 0
    )

    configured = _configured_sources(slug)
    sources_ready = bool(configured)
    pending = [
        f"{SOURCE_LABELS.get(plugin_id, plugin_id)}:{key}"
        for plugin_id, key in SOURCE_KEYS.items()
        if plugin_id not in configured
    ]

    steps = [
        {
            "key": "workspace",
            "title": "建工作区",
            "done": True,
            "detail": slug,
            "next": "",
        },
        {
            "key": "source",
            "title": "接入一个来源",
            "done": sources_ready,
            "detail": "、".join(sorted(SOURCE_LABELS.get(name, name) for name in configured)),
            "next": ""
            if sources_ready
            else "打开「信号源」页填令牌,或在这台机器上装好 GitHub App;缺的是:" + "、".join(pending[:3]),
        },
        {
            "key": "repo",
            "title": "接进一个仓库",
            "done": repos > 0,
            "detail": f"{repos} 个仓库",
            "next": "" if repos else "来源接通之后,给它一个投递(或点一次「同步」),仓库会自己冒出来",
        },
        {
            "key": "first-workflow",
            "title": "跑通第一条工作流",
            "done": changes > 0 or issues > 0,
            "detail": f"{issues} 条议题 / {changes} 条账",
            "next": ""
            if (changes > 0 or issues > 0)
            else "仓库进来之后,让来源发第一条议题进来;它会在议题板上出现",
        },
    ]
    return {
        "workspace": slug,
        "complete": all(step["done"] for step in steps),
        "steps": steps,
    }


__all__ = ["SOURCE_KEYS", "SOURCE_LABELS", "onboarding_status"]
