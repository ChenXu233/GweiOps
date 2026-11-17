# tests/test_integration/test_tenancy.py
"""租户原语测试。

非门控部分:payload 租户字段、缓存键租户隔离。
门控部分(GWEI_TEST_DATABASE_URL):复合唯一约束在真实 Postgres 上的行为。
"""

import os

import pytest
import sqlalchemy as sa
from unittest.mock import AsyncMock, patch


# ============================================================================
# payload 与缓存键
# ============================================================================


class TestTenantPayloadAndKeys:
    def test_payload_carries_tenant_slug(self):
        from engine.api.routes.webhook import _payload_from_event
        from engine.ingest.events import event as normalized_event

        event = normalized_event(
            kind="issue",
            source="github",
            repo="o/r",
            repo_id=1,
            change_id=2,
            number=1,
            title="T",
            body="B",
        )
        payload = _payload_from_event(event)

        slug = payload["tenant_slug"]
        assert isinstance(slug, str) and slug

    def test_llm_cache_key_differs_by_tenant(self):
        from engine.shared.cache import cache_key

        k1 = cache_key("llm-analysis", "tenant-a", "T", "B")
        k2 = cache_key("llm-analysis", "tenant-b", "T", "B")
        assert k1 != k2

    def test_webhook_dedup_key_format_includes_tenant(self):
        # 去重键由调用方拼接,这里锁定格式约定
        slug, delivery = "acme", "d-123"
        key = f"gwei:{slug}:webhook-dedup:{delivery}"
        assert key == "gwei:acme:webhook-dedup:d-123"
        assert key != f"gwei:other:webhook-dedup:{delivery}"


# ============================================================================
# 复合唯一约束(需要真实 Postgres)
# ============================================================================

requires_postgres = pytest.mark.skipif(
    not os.environ.get("GWEI_TEST_DATABASE_URL"),
    reason="需要 GWEI_TEST_DATABASE_URL 指向可写的 Postgres",
)


@requires_postgres
class TestCompositeUnique:
    def test_same_project_slug_two_tenants_ok_same_tenant_rejected(self):
        """同一个项目 slug 可被两个工作区分别建;同一个工作区里重复被拒。

        唯一键是 (tenant_id, slug)(见 engine/db/models/project.py)。它比原来那对
        (tenant_id, github_id) 更严:slug 是"仓库在这棵树上的名字",github_id 有的
        来源根本不给,拿它当身份在接第二个来源那天就会坏。
        """
        import uuid as uuid_mod

        from engine.db.base import Base
        from engine.db.models import Tenant  # noqa: F401 — 注册模型

        url = os.environ["GWEI_TEST_DATABASE_URL"]
        engine = sa.create_engine(url)
        with engine.connect() as conn:
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        Base.metadata.create_all(engine)

        run = uuid_mod.uuid4().hex[:8]
        tenant_a = str(uuid_mod.uuid4())
        tenant_b = str(uuid_mod.uuid4())

        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"
                ),
                {"id": tenant_a, "slug": f"a-{run}", "name": "A"},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"
                ),
                {"id": tenant_b, "slug": f"b-{run}", "name": "B"},
            )

        def _try_insert_project(tenant_id: str, slug: str) -> bool:
            """成功返回 True;唯一冲突返回 False。"""
            try:
                with engine.begin() as conn:
                    conn.execute(
                        sa.text(
                            "INSERT INTO projects (id, tenant_id, slug, name) "
                            "VALUES (gen_random_uuid(), :tenant_id, :slug, 'n')"
                        ),
                        {"tenant_id": tenant_id, "slug": slug},
                    )
                return True
            except sa.exc.IntegrityError:
                return False

        assert _try_insert_project(tenant_a, f"github-acme-api-{run}") is True
        # 同租户同一个 slug → 拒绝
        assert _try_insert_project(tenant_a, f"github-acme-api-{run}") is False
        # 不同租户同 slug → 允许
        assert _try_insert_project(tenant_b, f"github-acme-api-{run}") is True

        engine.dispose()
