# engine/db/tenancy.py
"""租户隔离的**一张清单**:哪张表归哪个工作区、按什么算。

行级安全要成立,靠的不是"每张表都开了策略",而是"新加一张表时有人会被拦下来"。
所以"一张表要不要隔离、怎么判"只写在这一处:

- 迁移 `020_rls_everywhere` 照 `isolated_tables()` 建策略;
- 启动时 `ensure_isolation()` 拿库里实际的策略与这份清单比对,缺了就拒绝启动;
- `.ci/engine-tests.py` 也读它,静态地对一遍 `Base.metadata`。

三个副本能同时漂,是因为它们读的是同一个函数,不是同一段文本。

**为什么清单要在代码里而不是库里**:新加一张表是写代码那一刻的事。写在库里,
就要有人记得同时往库里插一行——那正是"新表没有策略"的成因。
"""

from __future__ import annotations

import logging
from typing import Final

from sqlalchemy import text

logger = logging.getLogger(__name__)

POLICY_NAME: Final = "tenant_isolation"

# 租户从哪来。策略表达式一律以 `:scope` 收口 —— 会话变量没设时它是 NULL,
# 比较结果恒假,于是"忘了设"的默认结果是**什么都看不见**。
# 会话变量名。策略里读它们,连接层写它们(`engine/db/engine.py`)。
TENANT_SETTING: Final = "gwei.tenant"
PERSON_SETTING: Final = "gwei.person"
TENANT: Final = f"current_setting('{TENANT_SETTING}', true)"
# "不限"的值。连接层把明确跨工作区的请求写成它;策略里"为空或等于它"= 全放。
# 为空**不算**不限:那是"这条连接不知道自己在哪个工作区",默认应该是看不见。
ANY: Final = "'*'"
# "这次请求背后的人"。登录那条链自己设(它必须能读到这个人,否则连"我在哪几家"
# 都答不出来);业务查询不设,于是它们只看得到本工作区的人。
PERSON: Final = f"current_setting('{PERSON_SETTING}', true)"


def visible(scope: str) -> str:
    """`scope` 说的是"这一行属于哪个租户";这句说的是"这次能看见哪些行"。

    两条判据:连接明确声明了不限,或者这一行的租户与连接的工作区相等。
    `current_setting` 没设过时返回 NULL,`NULL = 任何值` 恒为假 —— 于是"没定"
    的默认结果是看不见,而不是看得见。
    """
    return f"{TENANT} = {ANY} OR {scope}"


def isolated_tables() -> dict[str, str]:
    """表名 → 策略表达式。顺序稳定(字典按插入序),迁移与校验都直接照它来。"""
    tenant = TENANT
    my_tenants = "(SELECT tenant_id::text FROM memberships WHERE person_id = persons.id)"

    table_scopes: dict[str, str] = {
        # ---- 工作区自己 ----
        "tenants": f"id::text = {tenant}",
        # ---- 直接带 tenant 字符串列 ----
        "change_events": f"tenant = {tenant}",
        "incidents": f"tenant = {tenant}",
        "plugin_settings": f"tenant = {tenant}",
        "plugin_tenancy": f"tenant = {tenant}",
        "api_keys": f"tenant = {tenant}",
        "console_sessions": f"tenant = {tenant}",
        "console_messages": f"tenant = {tenant}",
        # ---- 带 tenant_id ----
        "projects": f"tenant_id::text = {tenant}",
        "roles": f"tenant_id::text = {tenant}",
        "memberships": f"tenant_id::text = {tenant}",
        "user_sessions": f"tenant_id::text = {tenant}",
        "user_roles": f"tenant_id::text = {tenant}",
        "user_contacts": f"tenant_id::text = {tenant}",
        "user_activations": f"tenant_id::text = {tenant}",
        "password_reset_tokens": f"tenant_id::text = {tenant}",
        "external_identities": f"tenant_id::text = {tenant}",
        "verification_codes": f"tenant_id::text = {tenant}",
        "invitations": f"tenant_id::text = {tenant}",
        "project_settings": f"tenant_id::text = {tenant}",
        "quota_usage": f"tenant_id::text = {tenant}",
        # 审计与执行会话没有自己的租户列,经父表推
        "audit_log": (
            "actor_id IN (SELECT user_id FROM memberships "
            f"WHERE tenant_id::text = {tenant})"
        ),
        "agent_sessions": (
            f"issue_id IN (SELECT id FROM issues WHERE tenant_id::text = {tenant})"
        ),
        # ---- 只能由父表派生 ----
        "issues": f"tenant_id::text = {tenant}",
        "patches": (
            "session_id IN (SELECT s.id FROM agent_sessions s "
            f"JOIN issues i ON i.id = s.issue_id WHERE i.tenant_id::text = {tenant})"
        ),
        "pull_requests": (
            "patch_id IN (SELECT p.id FROM patches p "
            "JOIN agent_sessions s ON s.id = p.session_id "
            f"JOIN issues i ON i.id = s.issue_id WHERE i.tenant_id::text = {tenant})"
        ),
        "approval_votes": (
            "pr_id IN (SELECT pr.id FROM pull_requests pr "
            "JOIN patches p ON p.id = pr.patch_id "
            "JOIN agent_sessions s ON s.id = p.session_id "
            f"JOIN issues i ON i.id = s.issue_id WHERE i.tenant_id::text = {tenant})"
        ),
        # ---- 跨工作区只有一份,但同样要有边界 ----
        # `persons` 一行是"一个人",他可能属于好几个工作区。策略问的不是"属于谁"
        # 而是"谁能看见":自己那一行,或者本单位有成员关系的那几行。
        # 否则一次漏判,一个工作区就读到了另一个客户的全部员工名单。
        "persons": f"id = {PERSON}::uuid OR EXISTS {my_tenants}",
    }
    return {table: visible(scope) for table, scope in table_scopes.items()}


async def ensure_isolation(engine) -> list[str]:
    """启动时对一遍:清单里的表在库里都得有策略。缺了就返回那几张。

    不抛异常是刻意的 —— 调用方决定这是"拒绝启动"还是"只报警"。生产上是前者:
    一个不知道隔离有没有生效的 SaaS,比一个起不来的 SaaS 更贵。
    """
    names = list(isolated_tables())
    async with engine.connect() as conn:
        found = set(
            (
                await conn.execute(
                    text("SELECT tablename FROM pg_policies WHERE policyname = :name"),
                    {"name": POLICY_NAME},
                )
            ).scalars()
        )
    return [name for name in names if name not in found]


__all__ = [
    "POLICY_NAME",
    "PERSON",
    "PERSON_SETTING",
    "TENANT",
    "TENANT_SETTING",
    "ensure_isolation",
    "isolated_tables",
]
