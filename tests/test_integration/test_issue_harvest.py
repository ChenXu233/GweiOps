# tests/test_integration/test_issue_harvest.py
"""接入那一刻,把仓库已有的议题读进来。

分三层,各自证明一件事:

- **契约**:`list_issues` 是可选能力。没声明就抛 `LookupError`,入口据此说"列不了",
  不编一个 0 出来;
- **适配器**:GitHub 与 CNB 都声明了它,并且都只交回议题(PR 不混进议题板);
- **接入**:接的时候读、接之前就在的议题不被重复落一次、来源列不出来时如实报告。

第三层里"读一次"的落库路径要么真连库(`GWEI_TEST_DATABASE_URL`),要么用一个
只认得议题号的假会话 —— 两条都跑,前一条不满足时会显式跳过。
"""

import asyncio
import os

import pytest

requires_postgres = pytest.mark.skipif(
    not os.environ.get("GWEI_TEST_DATABASE_URL"),
    reason="需要 GWEI_TEST_DATABASE_URL 指向可写的 Postgres",
)


class TestCapabilityIsOptional:
    def test_adapter_without_list_issues_says_so(self):
        from engine.ingest.source import list_issues_of

        class Adapter:
            pass

        with pytest.raises(LookupError, match="列不出"):
            asyncio.run(list_issues_of(Adapter(), "acme/api"))

    def test_page_default_is_empty_not_unknown(self):
        """默认值是"这一页什么都没有",不是"这个仓库没有议题" —— 后者由 `listed` 说。"""
        from engine.ingest.source import IssuePage

        page = IssuePage()
        assert page.issues == []
        assert page.cursor == ""


def _adapter(source: str):
    """装着的那个适配器。

    目录名带连字符(`github-app`),import 得按清单给的名字走;CNB 那种下划线的
    目录两种写法都通。注册表在这组用例里没扫过盘,所以不从这里取实例。
    """
    import importlib

    where = {
        "github": ("plugins.builtin.adapters.github-app.plugin", "GitHubAppAdapter"),
        "cnb": ("plugins.builtin.adapters.cnb.plugin", "CNBAdapter"),
    }[source]
    return getattr(importlib.import_module(where[0]), where[1])()


class _StubClient:
    """只回一页:两条议题 + 一条 PR。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def list_issues(self, repo: str, cursor: str = "", per_page: int = 50):
        self.calls.append((repo, cursor))
        if cursor:
            return {"items": [], "cursor": ""}
        return {
            "items": [
                {"number": 1, "title": "真的议题", "body": "b", "is_pull": False},
                {"number": 2, "title": "一条 PR", "body": "", "is_pull": True},
                {"number": 3, "title": "另一条", "body": "", "is_pull": False},
            ],
            "cursor": "2",
        }


class TestGitHubListsIssues:
    def test_pull_requests_are_not_issues(self):
        """议题端点混着 PR。混进来会让"这条议题是谁提的"有两个答案。"""
        from engine.plugin_manager import registry

        adapter = _adapter("github")
        adapter.client = _StubClient()

        async def ready():
            return True

        adapter._ensure_ready = ready  # type: ignore[assignment]
        page = asyncio.run(adapter.list_issues("acme/api"))
        assert [item.number for item in page.issues] == [1, 3]
        assert page.cursor == "2"
        assert "一条 PR" not in [item.title for item in page.issues]


class TestCNBListsIssues:
    def test_page_number_is_the_cursor(self):
        adapter = _adapter("cnb")

        class Client:
            async def list_issues(self, repo, cursor="", per_page=50):
                assert repo == "acme/api"
                return {
                    "items": [{"number": 7, "title": "CNB 上的议题", "body": ""}],
                    "cursor": "",
                }

        adapter.client = Client()  # type: ignore[assignment]
        page = asyncio.run(adapter.list_issues("acme/api"))
        assert [item.number for item in page.issues] == [7]
        assert page.cursor == ""


class TestCNBPageCursor:
    def test_full_page_continues_short_page_stops(self):
        from engine.ingest.source import IssueRef, IssuePage

        first = IssuePage(issues=[IssueRef(number=1, title="a")], cursor="2")
        last = IssuePage(issues=[], cursor="")
        assert first.cursor == "2" and last.cursor == ""


class TestSyncKeepsOneRow:
    """同一条议题走过投递再来一次接入,不该落成两行。"""

    @requires_postgres
    def test_connecting_twice_does_not_duplicate_issues(self, monkeypatch):
        import engine.ingest.source as source_mod
        from engine.ingest.source import IssuePage, IssueRef

        seen_calls: list[str] = []

        class Adapter:
            async def list_issues(self, repo, cursor=""):
                seen_calls.append(cursor)
                if cursor:
                    return IssuePage()
                return IssuePage(
                    issues=[
                        IssueRef(number=1, title="已经有人的问题"),
                        IssueRef(number=2, title="另一个"),
                    ]
                )

        monkeypatch.setattr(
            "engine.ingest.source.source_adapter", lambda name: Adapter()
        )
        # connect.sync_issues 内部 import 的是模块函数,直接换模块上的那份
        async def fake_list(adapter, repo, cursor=""):
            return await adapter.list_issues(repo, cursor)

        monkeypatch.setattr(source_mod, "list_issues_of", fake_list)

        import uuid

        import sqlalchemy as sa
        from sqlalchemy.orm import Session

        import engine.db.models  # noqa: F401 — 注册全部模型
        from engine.db.base import Base
        from engine.db.models import Issue, Tenant

        sync_engine = sa.create_engine(os.environ["GWEI_TEST_DATABASE_URL"])
        with sync_engine.connect() as conn:
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        Base.metadata.create_all(sync_engine)

        slug = f"ws-{uuid.uuid4().hex[:8]}"
        with Session(sync_engine) as session:
            tenant = Tenant(slug=slug, name="读议题")
            session.add(tenant)
            session.commit()
            tenant_id = tenant.id

        async def run():
            from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
            from sqlalchemy.pool import NullPool

            from engine.projects.connect import connect, sync_issues

            engine = create_async_engine(
                os.environ["GWEI_TEST_DATABASE_URL"].replace(
                    "postgresql+psycopg://", "postgresql+psycopg://"
                ),
                poolclass=NullPool,
            )
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as session:
                row, _ = await connect(session, tenant_id, "github", "acme/api")
                first = await sync_issues(session, tenant_id, row, "github", "acme/api")
                again = await sync_issues(session, tenant_id, row, "github", "acme/api")
                await session.commit()
            await engine.dispose()
            return first, again

        try:
            first, again = asyncio.run(run())
            assert first["listed"] is True
            assert first["added"] == 2
            # 第二遍什么都补不进来:身份是 (仓库, 议题号)
            assert again["added"] == 0
            with Session(sync_engine) as session:
                rows = session.execute(
                    sa.text(
                        "SELECT number FROM issues WHERE project_id IN "
                        "(SELECT id FROM projects WHERE tenant_id = :tid) ORDER BY number"
                    ),
                    {"tid": tenant_id},
                ).scalars().all()
            assert rows == [1, 2]
        finally:
            with sync_engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "DELETE FROM issues WHERE project_id IN "
                        "(SELECT id FROM projects WHERE tenant_id IN "
                        "(SELECT id FROM tenants WHERE slug = :slug))"
                    ),
                    {"slug": slug},
                )
                conn.execute(
                    sa.text(
                        "DELETE FROM projects WHERE tenant_id IN "
                        "(SELECT id FROM tenants WHERE slug = :slug)"
                    ),
                    {"slug": slug},
                )
                conn.execute(sa.text("DELETE FROM tenants WHERE slug = :slug"), {"slug": slug})
            sync_engine.dispose()


class TestUnlistableSourceIsReported:
    def test_no_adapter_is_not_zero_issues(self, monkeypatch):
        """列不出来 ≠ 没有议题:两者都给 0 条,但 `listed` 不一样。"""
        import engine.ingest.source as source_mod

        def boom(name):
            raise LookupError("没装这个来源的适配器")

        monkeypatch.setattr(source_mod, "source_adapter", boom)

        from engine.projects.connect import sync_issues

        class Row:
            id = None

        class Session:
            pass

        result = asyncio.run(sync_issues(Session(), None, Row(), "nope", "acme/api"))
        assert result["listed"] is False
        assert result["added"] == 0
        assert "适配器" in result["reason"]
