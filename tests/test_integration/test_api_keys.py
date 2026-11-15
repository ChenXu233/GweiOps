# tests/test_integration/test_api_keys.py
"""密钥 —— 外界 agent 的凭据:单独签发、单独吊销、工具按它暴露。

这里的判据都不是"接口返回 200",而是三件事实:
- 明文只出现一次,库里只有哈希与 hint;
- 吊销之后立刻认不出;
- 一把密钥的工具清单 = 它的权限够得着的那些,不多不少。
"""

from __future__ import annotations

import asyncio

import pytest

from engine.auth import ALL_PERMISSIONS
from engine.auth import keys as key_store
from engine.auth.keys import KeyRecord, permission_for_tool, tool_allowed
from engine.shared.config import config


@pytest.fixture
def file_backend(tmp_path, monkeypatch):
    """密钥与账本共用同一个开关:file 后端不碰库,测试才不需要 Postgres。"""
    monkeypatch.setattr(config.settings, "change_ledger_backend", "file")
    monkeypatch.setattr(config.settings, "change_ledger_path", str(tmp_path / "ledger.jsonl"))
    return tmp_path


class FakeActor:
    """与 engine.api.auth.Actor 同一个形状:static=True 表示只带 scope 的静态令牌。"""

    def __init__(self, *, permissions=(), tools=(), scope="read", static=False):
        self.permissions = frozenset(permissions)
        self.tools = frozenset(tools)
        self.scope = scope
        self.static = static

    @property
    def scoped(self) -> bool:
        return not self.static


# ---------------------------------------------------------------------------
# 能力名 → 权限
# ---------------------------------------------------------------------------


def test_a_read_tool_wants_a_read_permission():
    assert permission_for_tool("changes.read") == "changes.read"
    assert permission_for_tool("incidents.read") == "changes.read"


def test_an_effect_wants_the_exit_permission():
    assert permission_for_tool("compose.scale") == "changes.execute"
    assert permission_for_tool("pr.open") == "changes.execute"


def test_an_unknown_read_suffix_falls_back_to_read():
    """新增一个只读能力不必回来改表:后缀就是判据。"""
    assert permission_for_tool("whatever.read") == "changes.read"


def test_no_identity_means_no_filtering():
    """没配凭据的部署不筛 —— 单机自用的老行为,不能因为加了密钥就变。"""
    assert tool_allowed("compose.scale", None)
    assert tool_allowed("changes.read", None)


def test_permissions_narrow_the_list():
    actor = FakeActor(permissions={"changes.read"})
    assert tool_allowed("changes.read", actor)
    assert not tool_allowed("compose.scale", actor)


def test_the_whitelist_narrows_further():
    """权限够了,但白名单只点了这一样:别的就不给。"""
    actor = FakeActor(permissions=ALL_PERMISSIONS, tools={"compose.scale"})
    assert tool_allowed("compose.scale", actor)
    assert not tool_allowed("changes.read", actor)


def test_a_static_read_token_only_sees_read_tools():
    assert not tool_allowed("compose.scale", FakeActor(scope="read", static=True))
    assert tool_allowed("changes.read", FakeActor(scope="read", static=True))
    assert tool_allowed("compose.scale", FakeActor(scope="operate", static=True))


def test_a_key_with_no_permissions_sees_nothing():
    """空权限集是"什么都没有",不是"全都有" —— 这把密钥必须是零权限。"""
    actor = FakeActor()
    assert not tool_allowed("compose.scale", actor)
    assert not tool_allowed("changes.read", actor)


# ---------------------------------------------------------------------------
# 签发、解析、吊销
# ---------------------------------------------------------------------------


def test_the_plaintext_never_lands_in_the_store(file_backend):
    record, plaintext = asyncio.run(
        key_store.create_key(tenant="acme", name="claude-code", permissions=["changes.read"])
    )

    assert plaintext.startswith(key_store.KEY_PREFIX)
    stored = (file_backend / "api-keys.json").read_text(encoding="utf-8")
    assert plaintext not in stored
    assert key_store.hash_key(plaintext) in stored
    assert record.hint in stored
    assert record.hint != plaintext


def test_a_key_resolves_to_its_permissions(file_backend):
    record, plaintext = asyncio.run(
        key_store.create_key(
            tenant="acme", name="cursor", permissions=["changes.read", "changes.execute"]
        )
    )

    found = asyncio.run(key_store.resolve_key(plaintext))

    assert found is not None
    assert found.id == record.id
    assert found.permissions == {"changes.read", "changes.execute"}


def test_unknown_permissions_are_dropped(file_backend):
    record, _ = asyncio.run(
        key_store.create_key(tenant="acme", name="x", permissions=["changes.read", "made.up"])
    )
    assert record.permissions == {"changes.read"}


def test_a_revoked_key_stops_resolving(file_backend):
    record, plaintext = asyncio.run(
        key_store.create_key(tenant="acme", name="leaked", permissions=["changes.read"])
    )
    assert asyncio.run(key_store.resolve_key(plaintext)) is not None

    assert asyncio.run(key_store.revoke_key("acme", record.id)) is True
    assert asyncio.run(key_store.resolve_key(plaintext)) is None


def test_another_tenant_cannot_revoke_it(file_backend):
    record, plaintext = asyncio.run(
        key_store.create_key(tenant="acme", name="k", permissions=["changes.read"])
    )
    assert asyncio.run(key_store.revoke_key("other", record.id)) is False
    assert asyncio.run(key_store.resolve_key(plaintext)) is not None


def test_an_expired_key_is_recognized_but_refused(file_backend):
    _, plaintext = asyncio.run(
        key_store.create_key(
            tenant="acme",
            name="short-lived",
            permissions=["changes.read"],
            expires_at="2000-01-01T00:00:00+00:00",
        )
    )
    assert asyncio.run(key_store.resolve_key(plaintext)) is None


def test_a_broken_expiry_is_refused_at_issue_time(file_backend):
    """读不懂的到期时间在签发时就拒,比存进去再猜要好。"""
    with pytest.raises(key_store.KeyError_):
        asyncio.run(key_store.create_key(tenant="acme", name="odd", expires_at="明天"))


def test_a_key_needs_a_name(file_backend):
    with pytest.raises(key_store.KeyError_):
        asyncio.run(key_store.create_key(tenant="acme", name="  "))


def test_a_random_string_is_not_a_key(file_backend):
    assert asyncio.run(key_store.resolve_key("not-a-key")) is None
    assert asyncio.run(key_store.resolve_key(key_store.KEY_PREFIX + "nope")) is None


def test_listing_is_per_tenant_and_never_shows_the_plaintext(file_backend):
    asyncio.run(key_store.create_key(tenant="acme", name="a", permissions=["changes.read"]))
    asyncio.run(key_store.create_key(tenant="other", name="b", permissions=["changes.read"]))

    mine = asyncio.run(key_store.list_keys("acme"))

    assert [record.name for record in mine] == ["a"]
    assert all(isinstance(record, KeyRecord) for record in mine)
    assert "key" not in mine[0].to_dict()


# ---------------------------------------------------------------------------
# 业务库那一份(需要 GWEI_TEST_DATABASE_URL)
# ---------------------------------------------------------------------------


requires_postgres = pytest.mark.skipif(
    not __import__("os").environ.get("GWEI_TEST_DATABASE_URL"),
    reason="需要 GWEI_TEST_DATABASE_URL 指向可写的 Postgres",
)


@requires_postgres
def test_the_db_store_round_trips(monkeypatch):
    """数据库那一份要和文件那份同样的行为:只存哈希、吊销即失效、按租户隔离。"""
    from engine.db.models.api_key import ApiKey
    from engine.db.base import Base
    import sqlalchemy as sa
    import os

    sync_engine = sa.create_engine(os.environ["GWEI_TEST_DATABASE_URL"])
    Base.metadata.create_all(sync_engine, tables=[ApiKey.__table__])
    sync_engine.dispose()

    monkeypatch.setattr(config.settings, "change_ledger_backend", "db")
    store = key_store.DbKeyStore()

    record, plaintext = asyncio.run(
        key_store.create_key(tenant="acme", name="db-key", permissions=["changes.read"])
    )
    found = asyncio.run(key_store.resolve_key(plaintext))
    assert found is not None and found.id == record.id
    # 库里是哈希,不是明文
    assert asyncio.run(store.find(key_store.hash_key(plaintext))) is not None
    assert asyncio.run(store.find(plaintext)) is None

    assert asyncio.run(key_store.revoke_key("acme", record.id)) is True
    assert asyncio.run(key_store.resolve_key(plaintext)) is None
