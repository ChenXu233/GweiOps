"""开过策略的库上,隔离是不是真成立。需要 GWEI_TEST_DATABASE_URL。

单元用例只能证明"清单没漏",证明不了"策略真的在拦"。这一条在真库上问三件事:

1. 一个工作区的连接读不到另一个工作区的行;
2. 连接不声明工作区时一行都读不到(默认拒绝,不是默认放行);
3. 明确声明"不限"时才读得到全部 —— 这是认证那条链要的路,别的路不该有。
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

requires_postgres = pytest.mark.skipif(
    not os.environ.get("GWEI_TEST_DATABASE_URL"),
    reason="需要 GWEI_TEST_DATABASE_URL 指向可写的 Postgres",
)


def _ensure_schema() -> str:
    """在独立库上把迁移跑到头。与 test_plugin_data 的做法一致:策略是迁移给的,
    `create_all` 建出来的裸表测不出真东西。"""
    import logging.config

    import sqlalchemy as sa

    url = os.environ["GWEI_TEST_DATABASE_URL"]
    admin_url = sa.engine.make_url(url).set(database="gwei_admin")
    name = f"gwei_iso_{uuid.uuid4().hex[:8]}"
    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(
                sa.text(
                    f'CREATE DATABASE "{name}" TEMPLATE template0 ENCODING \'UTF8\' '
                    "LC_COLLATE 'C' LC_CTYPE 'C'"
                )
            )
    finally:
        admin.dispose()

    fresh = str(sa.engine.make_url(url).set(database=name))
    from alembic import command
    from alembic.config import Config

    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "engine" / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "engine" / "migrations"))
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = fresh
    real_file_config = logging.config.fileConfig
    logging.config.fileConfig = lambda *a, **k: None
    try:
        command.upgrade(cfg, "head")
    finally:
        logging.config.fileConfig = real_file_config
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
    return fresh


@requires_postgres
def test_a_session_sees_only_its_own_workspace():
    import sqlalchemy as sa

    fresh = _ensure_schema()
    engine = sa.create_engine(fresh)
    run = uuid.uuid4().hex[:8]
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO change_events (unit_id, tenant, binding, verdict, "
                    "idempotency_key, created_at, payload) VALUES "
                    "(:u, :t, 'local', 'kept', :k, '2026-01-01T00:00:00Z', '{}')"
                ),
                [
                    {"u": f"a-{run}", "t": f"acme-{run}", "k": f"k-{run}-a"},
                    {"u": f"b-{run}", "t": f"other-{run}", "k": f"k-{run}-b"},
                ],
            )

        def count(tenant: str | None, unit: str | None = None) -> int:
            with engine.connect() as conn:
                conn.execute(sa.text("SET ROLE gwei_plugin_reader"))
                if tenant is not None:
                    conn.execute(
                        sa.text("SELECT set_config('gwei.tenant', :t, true)"), {"t": tenant}
                    )
                stmt = "SELECT count(*) FROM v_plugin_changes"
                params: dict = {}
                if unit is not None:
                    stmt += " WHERE unit_id = :u"
                    params = {"u": unit}
                out = conn.execute(sa.text(stmt), params).scalar_one()
                conn.rollback()
                return out

        # 自己的那条看得见,别人的看不见
        assert count(f"acme-{run}", f"a-{run}") == 1
        assert count(f"acme-{run}", f"b-{run}") == 0
        # 不声明工作区:零行。默认拒绝,不是默认放行。
        assert count(None) == 0
        # 明确不限:两条都在
        assert count("*") == 2
    finally:
        engine.dispose()
        drop = sa.create_engine(
            sa.engine.make_url(os.environ["GWEI_TEST_DATABASE_URL"]).set(database="gwei_admin"),
            isolation_level="AUTOCOMMIT",
        )
        name = sa.engine.make_url(fresh).database
        try:
            with drop.connect() as conn:
                conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}"'))
        finally:
            drop.dispose()


@requires_postgres
def test_the_manifest_reaches_the_database():
    """清单里的每一张表在库里都真有策略。缺一张,启动那条检查会拒绝起来。"""
    import sqlalchemy as sa

    from engine.db.tenancy import POLICY_NAME, isolated_tables

    fresh = _ensure_schema()
    engine = sa.create_engine(fresh)
    try:
        with engine.connect() as conn:
            found = set(
                (
                    conn.execute(
                        sa.text("SELECT tablename FROM pg_policies WHERE policyname = :n"),
                        {"n": POLICY_NAME},
                    )
                ).scalars()
            )
        assert sorted(set(isolated_tables()) - found) == []
        # 清单也要落到库里那份:应用启动时与它比对
        with engine.connect() as conn:
            recorded = set(
                (conn.execute(sa.text("SELECT table_name FROM tenancy_policy_manifest"))).scalars()
            )
        assert recorded == set(isolated_tables())
    finally:
        engine.dispose()
        drop = sa.create_engine(
            sa.engine.make_url(os.environ["GWEI_TEST_DATABASE_URL"]).set(database="gwei_admin"),
            isolation_level="AUTOCOMMIT",
        )
        name = sa.engine.make_url(fresh).database
        try:
            with drop.connect() as conn:
                conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}"'))
        finally:
            drop.dispose()
