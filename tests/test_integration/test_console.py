# tests/test_integration/test_console.py
"""控制台剩下的两个读取点 —— 需要 GWEI_TEST_DATABASE_URL(真实 Postgres)。

议题与变更各有自己的测试;这里只管仓库列表与团队设置这两个没有别处可去的接口。
"""

import os

import pytest

requires_postgres = pytest.mark.skipif(
    not os.environ.get("GWEI_TEST_DATABASE_URL"),
    reason="需要 GWEI_TEST_DATABASE_URL 指向可写的 Postgres",
)


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from engine.api.app import app
    from engine.plugin_manager import registry

    # 自足建表:不依赖其他门控测试先跑过 create_all——测试顺序不是契约。
    if os.environ.get("GWEI_TEST_DATABASE_URL"):
        import sqlalchemy as sa

        import engine.db.models  # noqa: F401 — 注册全部模型
        from engine.db.base import Base

        sync_engine = sa.create_engine(os.environ["GWEI_TEST_DATABASE_URL"])
        with sync_engine.connect() as conn:
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        Base.metadata.create_all(sync_engine)
        sync_engine.dispose()

    if not registry.names():
        registry.discover()
    return TestClient(app)


@requires_postgres
class TestConsole:
    def test_repos_and_settings(self, client):
        repos = client.get("/api/repos").json()
        for repo in repos:
            assert {"id", "name", "issueCount", "status"} <= set(repo)

        settings = client.get("/api/settings").json()
        assert settings["plan"] == "selfhost"

    def test_retired_aggregates_are_gone(self, client):
        """控制室与执行记录两个页面没了,它们的聚合接口也不该还挂着。"""
        for path in ("/api/dashboard", "/api/dashboard/pending", "/api/runs", "/api/issues"):
            assert client.get(path).status_code == 404, path

    def test_workspaces_list_carries_repo_counts(self, client):
        """工作区列表带上每个里面有几个仓库、来自哪些平台——侧边栏靠它显示。"""
        import uuid

        import sqlalchemy as sa
        from sqlalchemy.orm import Session

        from engine.db.models import Project, Tenant

        slug = f"ws-{uuid.uuid4().hex[:8]}"
        engine = sa.create_engine(os.environ["GWEI_TEST_DATABASE_URL"])
        try:
            with Session(engine) as db:
                tenant = Tenant(slug=slug, name="多仓库工作区")
                db.add(tenant)
                db.flush()
                for name, source in (("acme/web", "github"), ("acme/api", "cnb")):
                    db.add(
                        Project(
                            tenant_id=tenant.id,
                            source=source,
                            name=name,
                            slug=f"{source}:{name}",
                        )
                    )
                db.commit()
        finally:
            engine.dispose()

        data = client.get("/api/workspaces").json()
        row = next(w for w in data["items"] if w["slug"] == slug)
        assert row["repos"] == 2
        assert row["sources"] == ["cnb", "github"]

    def test_repo_identity_is_source_plus_name(self, client):
        """同一仓库名在两个来源上是两份数据:平台侧的数字 id 不是身份。"""
        import uuid

        import sqlalchemy as sa
        from sqlalchemy.orm import Session

        from engine.db.models import Project, Tenant

        slug = f"ws-{uuid.uuid4().hex[:8]}"
        name = f"acme/dup-{uuid.uuid4().hex[:6]}"
        engine = sa.create_engine(os.environ["GWEI_TEST_DATABASE_URL"])
        try:
            with Session(engine) as db:
                tenant = Tenant(slug=slug, name="同名仓库")
                db.add(tenant)
                db.flush()
                # 来源不同的两行,名字一样;id 都没有(有的来源根本不给)
                db.add(Project(tenant_id=tenant.id, source="github", name=name, slug=f"github:{name}"))
                db.add(Project(tenant_id=tenant.id, source="gitlab", name=name, slug=f"gitlab:{name}"))
                db.commit()
        finally:
            engine.dispose()

        repos = client.get("/api/repos", params={"workspace": slug}).json()
        assert sorted(r["source"] for r in repos) == ["github", "gitlab"]

    def test_repos_carry_their_project(self, client):
        """仓库上面还有项目:每行说清自己属于谁,范围闸的中间档才立得住。"""
        import uuid

        import sqlalchemy as sa
        from sqlalchemy.orm import Session

        from engine.db.models import Project, Tenant

        slug = f"ws-{uuid.uuid4().hex[:8]}"
        project = f"acme-{uuid.uuid4().hex[:6]}"
        engine = sa.create_engine(os.environ["GWEI_TEST_DATABASE_URL"])
        try:
            with Session(engine) as db:
                tenant = Tenant(slug=slug, name="有项目的工作区")
                db.add(tenant)
                db.flush()
                parent = Project(
                    tenant_id=tenant.id, parent_id=None, slug=project, source="", name="Acme"
                )
                db.add(parent)
                db.flush()
                db.add(
                    Project(
                        tenant_id=tenant.id,
                        parent_id=parent.id,
                        slug=f"github:{project}/api",
                        source="github",
                        name=f"{project}/api",
                    )
                )
                db.commit()
        finally:
            engine.dispose()

        repos = client.get("/api/repos", params={"workspace": slug}).json()
        # 项目行不是仓库:列表里只该有那个子仓
        assert [r["name"] for r in repos] == [f"{project}/api"]
        assert repos[0]["project"] == project
        assert repos[0]["projectName"] == "Acme"

        projects = client.get("/api/projects", params={"workspace": slug}).json()["items"]
        row = next(p for p in projects if p["slug"] == project)
        assert row["repos"] == 1
