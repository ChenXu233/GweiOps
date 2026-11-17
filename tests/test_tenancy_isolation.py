"""租户隔离这份清单本身的判据。

策略写在迁移里,但"哪些表要有策略"只能由代码回答 —— 新加一张表是写代码那一刻的
事,写进库里就要有人记得同时插一行,而那正是漏的成因。这几条用例盯的是清单与
模型之间不漂。
"""

from __future__ import annotations

import engine.db.models  # noqa: F401 — 注册全部模型
from engine.db.base import Base
from engine.db.tenancy import ANY, isolated_tables, visible


def test_every_table_with_a_tenant_column_is_registered():
    """带 tenant / tenant_id 的表都得在清单里。漏一张 = 共享部署里谁都能读。"""
    covered = set(isolated_tables())
    unregistered = sorted(
        name
        for name, table in Base.metadata.tables.items()
        if {"tenant", "tenant_id"} & {column.name for column in table.columns}
        and name not in covered
    )
    assert unregistered == []


def test_the_manifest_only_names_real_tables():
    """清单里的名字都得是真表:删了表忘了删清单,迁移会红在更晚的地方。"""
    unknown = sorted(set(isolated_tables()) - set(Base.metadata.tables))
    assert unknown == []


def test_every_policy_says_what_happens_when_the_tenant_is_unset():
    """每条策略都带"明确不限"那一档,别的地方不重复写。

    连接层把"不限"写成 `*`;策略说"为空或等于 `*`"才是全放。少了前半句,
    明确不限的会话照样一行读不到(静默的 0 行);少了后半句,它读到的是全部
    但又和"没定"混在一起 —— 两种错都不会报错。
    """
    for table, expression in isolated_tables().items():
        assert expression.startswith(f"current_setting('gwei.tenant', true) = {ANY}"), table
        # 值必须与 `engine/db/engine.py` 的 `ANY_TENANT` 一致
    from engine.db.engine import ANY_TENANT

    assert ANY == f"'{ANY_TENANT}'"


def test_visible_is_the_only_place_that_wraps_a_scope():
    """表达式由 `visible()` 包一层,迁移与校验读的是同一段文本。"""
    assert visible("tenant = 'x'") == (
        "current_setting('gwei.tenant', true) = '*' OR tenant = 'x'"
    )
