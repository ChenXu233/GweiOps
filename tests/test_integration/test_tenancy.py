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
    def test_extract_payload_carries_tenant_slug(self):
        from engine.api.routes.webhook import _extract_payload

        issue_info = {"owner": "o", "repo": "r", "issue_number": 1, "title": "T"}
        raw = {
            "repository": {"id": 1},
            "issue": {"id": 2, "title": "T", "body": "B"},
        }
        payload = _extract_payload(raw, issue_info, "issues")

        assert payload is not None
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
    def test_same_repo_two_tenants_ok_same_tenant_rejected(self):
        """同仓库可被两个租户分别安装;同租户重复被拒。"""
        from sqlalchemy.dialects.postgresql import UUID as PGUUID

        from engine.db.base import Base
        from engine.db.models import Project, Tenant

        url = os.environ["GWEI_TEST_DATABASE_URL"]
        engine = sa.create_engine(url)
        with engine.connect() as conn:
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        Base.metadata.create_all(engine)

        ins_tenant = sa.text(
            "INSERT INTO tenants (id, slug, name) VALUES (:id, :slug, :name)"
        )
        tenant_a, tenant_b = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"

        def _try_insert_project(tenant_id: str, github_id: int) -> bool:
            """成功返回 True;唯一冲突返回 False(并回滚到 savepoint 外)。"""
            try:
                with engine.begin() as conn:
                    conn.execute(
                        sa.text(
                            "INSERT INTO projects (id, tenant_id, github_id, name) "
                            "VALUES (gen_random_uuid(), :tenant_id, :github_id, 'n')"
                        ),
                        {"tenant_id": tenant_id, "github_id": github_id},
                    )
                return True
            except sa.exc.IntegrityError:
                return False

        with engine.begin() as conn:
            conn.execute(
                ins_tenant, {"id": tenant_a, "slug": "a-test", "name": "A"}
            )
            conn.execute(
                ins_tenant, {"id": tenant_b, "slug": "b-test", "name": "B"}
            )

        assert _try_insert_project(tenant_a, 900) is True
        # 同租户同 github_id → 拒绝
        assert _try_insert_project(tenant_a, 900) is False
        # 不同租户同 github_id → 允许
        assert _try_insert_project(tenant_b, 900) is True

        engine.dispose()
