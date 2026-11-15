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
