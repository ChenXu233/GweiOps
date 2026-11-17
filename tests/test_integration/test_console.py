# tests/test_integration/test_console.py
"""控制台剩下的读取点 —— 需要 GWEI_TEST_DATABASE_URL(真实 Postgres)。

议题与变更各有自己的测试;这里只管工作区、仓库列表、项目与团队设置这几个没有
别处可去的接口。工作区写在路径里:{workspace}/repos 就是那个工作区的仓库。
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


def _drop_tenant_rows(slug: str) -> None:
    """删掉这条用例建的那几行。

    库上要是开着策略(跑过迁移的那个库),读完不清会让下一条用例读到别人的行:
    几条用例都建"名字一样"的仓库,断言按名字数数就会数多。
    """
    import sqlalchemy as sa

    engine = sa.create_engine(os.environ["GWEI_TEST_DATABASE_URL"])
    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "DELETE FROM projects WHERE tenant_id IN "
                    "(SELECT id FROM tenants WHERE slug = :slug)"
                ),
                {"slug": slug},
            )
            conn.execute(sa.text("DELETE FROM tenants WHERE slug = :slug"), {"slug": slug})
    finally:
        engine.dispose()


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
                            slug=f"{source}-{name.replace('/', '-')}",
                        )
                    )
                db.commit()
        finally:
            engine.dispose()

        try:
            data = client.get("/api/workspaces").json()
        finally:
            _drop_tenant_rows(slug)
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
                # 来源不同的两行、名字一样;slug 的写法是 `来源-仓库全名`(`/` 压成 `-`,
                # 见 engine/workflows/pipeline.py 的 repo_slug)。它是 (租户, slug) 上的
                # 唯一键 —— 也就是"名字撞了仍然是两个仓库"这件事在库里的表达。
                # 仓库挂在项目下面(`parent_id` 非空),仓库列表只列这一种行。
                parent = Project(tenant_id=tenant.id, parent_id=None, slug=f"p-{slug}", source="", name="同名仓库")
                db.add(parent)
                db.flush()
                db.add(Project(tenant_id=tenant.id, parent_id=parent.id, source="github", name=name, slug=f"github-{name.replace('/', '-')}"))
                db.add(Project(tenant_id=tenant.id, parent_id=parent.id, source="gitlab", name=name, slug=f"gitlab-{name.replace('/', '-')}"))
                db.commit()
        finally:
            engine.dispose()

        repos = client.get(f"/api/workspaces/{slug}/repos").json()
        _drop_tenant_rows(slug)
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
                        slug=f"github-{project}-api",
                        source="github",
                        name=f"{project}/api",
                    )
                )
                db.commit()
        finally:
            engine.dispose()

        repos = client.get(f"/api/workspaces/{slug}/repos").json()
        # 项目列表与仓库列表分开取自:**先**取仓库。`/repos` 已经在这个客户端上
        # 跑过一遍时,再跑 `/projects` 会撞上 asyncpg "attached to a different loop"
        # (两条读取各自的连接池与事件循环对不上)。这条顺序不是这个用例要证的东西,
        # 但换了顺序它就红得很响、且与它要证的事无关。
        projects = client.get(f"/api/workspaces/{slug}/projects").json()["items"]
        _drop_tenant_rows(slug)
        # 项目行不是仓库:列表里只该有那个子仓
        assert [r["name"] for r in repos] == [f"{project}/api"]
        assert repos[0]["project"] == project
        assert repos[0]["projectName"] == "Acme"

        row = next(p for p in projects if p["slug"] == project)
        assert row["repos"] == 1
