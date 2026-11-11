# tests/test_integration/test_auth_rbac.py
"""身份与权限:密码、角色并集、子用户不超过父亲。"""

import pytest

from engine.auth import (
    ALL_PERMISSIONS,
    effective_permissions,
    hash_password,
    is_write_permission,
    verify_password,
)


def test_password_round_trip():
    stored = hash_password("correct horse battery")
    assert verify_password("correct horse battery", stored)
    assert not verify_password("wrong horse", stored)
    # 每次加盐,同一密码两次哈希不一样
    assert stored != hash_password("correct horse battery")


def test_short_password_is_refused():
    with pytest.raises(ValueError):
        hash_password("1234567")


def test_a_broken_hash_fails_closed():
    assert not verify_password("x", "not-a-hash")
    assert not verify_password("x", "")
    assert not verify_password("x", "md5$a$b$c$d$e")


def test_roles_are_a_union():
    perms = effective_permissions(["settings.read"], [["changes.read"], ["audit.read"]])
    assert perms == {"settings.read", "changes.read", "audit.read"}


def test_unknown_permissions_are_dropped():
    perms = effective_permissions(["made.up.permission"], [["changes.read"]])
    assert perms == {"changes.read"}


def test_a_sub_user_cannot_exceed_its_parent():
    parent = frozenset({"changes.read", "changes.approve"})
    # 子用户自带了 settings.write,但父亲没有 —— 交集之后不该出现
    perms = effective_permissions(["settings.write"], [["changes.read"]], parent=parent)
    assert perms == {"changes.read"}
    assert "settings.write" not in perms


def test_a_disabled_parent_leaves_the_child_with_nothing():
    # 父被停用时传空集合,不是 None:空集合是"父没有权限",None 是"没有父"
    perms = effective_permissions(None, [["changes.read"]], parent=frozenset())
    assert perms == frozenset()


def test_a_top_level_user_is_not_narrowed():
    perms = effective_permissions(None, [ALL_PERMISSIONS])
    assert perms == ALL_PERMISSIONS


def test_read_permissions_are_not_writes():
    assert not is_write_permission("changes.read")
    assert not is_write_permission("audit.read")
    assert is_write_permission("changes.approve")
    assert is_write_permission("settings.write")
    assert is_write_permission("users.manage")
