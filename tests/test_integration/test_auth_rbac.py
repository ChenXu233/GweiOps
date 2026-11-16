# tests/test_integration/test_auth_rbac.py
"""身份与权限:密码、角色并集、子用户不超过父亲。"""

import pytest

from engine.auth import (
    ALL_PERMISSIONS,
    Identity,
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
    perms, scoped = effective_permissions(["settings.read"], [["changes.read"], ["audit.read"]])
    assert perms == {"settings.read", "changes.read", "audit.read"}
    assert scoped == {}


def test_unknown_permissions_are_dropped():
    perms, _ = effective_permissions(["made.up.permission"], [["changes.read"]])
    assert perms == {"changes.read"}


def test_a_sub_user_cannot_exceed_its_parent():
    parent = frozenset({"changes.read", "changes.approve"})
    # 子用户自带了 settings.write,但父亲没有 —— 交集之后不该出现
    perms, _ = effective_permissions(["settings.write"], [["changes.read"]], parent=parent)
    assert perms == {"changes.read"}
    assert "settings.write" not in perms


def test_a_disabled_parent_leaves_the_child_with_nothing():
    # 父被停用时传空集合,不是 None:空集合是"父没有权限",None 是"没有父"
    perms, _ = effective_permissions(None, [["changes.read"]], parent=frozenset())
    assert perms == frozenset()


def test_a_top_level_user_is_not_narrowed():
    perms, _ = effective_permissions(None, [ALL_PERMISSIONS])
    assert perms == ALL_PERMISSIONS


def test_a_scoped_grant_is_not_a_workspace_grant():
    """`changes.approve@acme/api` 只在那个仓库算数,不能当工作区级权限用。"""
    perms, scoped = effective_permissions(["changes.approve@github-acme-api"], [])
    assert perms == frozenset()
    assert scoped == {"changes.approve": frozenset({"github-acme-api"})}

    identity = Identity(user_id="u", name="n", tenant="t", permissions=perms, scoped_permissions=scoped)
    assert not identity.has("changes.approve")
    assert identity.allows("changes.approve", "github-acme-api")
    assert not identity.allows("changes.approve", "github-acme-web")
    # 不点名一个仓库 = 整个工作区,这里不该放行
    assert not identity.allows("changes.approve", None)
    assert not identity.allows("changes.approve", "")
    # 只授了一个仓库的写权限,界面上他仍要看得见那些按钮
    assert identity.can_write


def test_a_permission_that_cannot_be_scoped_is_not_scoped():
    """收窄 `users.manage` 没有意义:一个仓库没有自己的用户表。丢掉,不猜。"""
    perms, scoped = effective_permissions(["users.manage@github-acme-api"], [])
    assert perms == frozenset()
    assert scoped == {}
    # 没写清楚收窄到哪也一样丢掉
    assert effective_permissions(["changes.approve@"], []) == (frozenset(), {})


def test_workspace_and_scoped_grants_add_up():
    """工作区级那份管别的仓库,带范围那份只管这几个,两者不互相吞掉。"""
    perms, scoped = effective_permissions(
        ["changes.approve", "changes.approve@github-acme-api"], []
    )
    identity = Identity(user_id="u", name="n", tenant="t", permissions=perms, scoped_permissions=scoped)
    assert identity.allows("changes.approve", None)
    assert identity.allows("changes.approve", "github-acme-api")
    assert identity.allows("changes.approve", "任意仓库")


def test_a_sub_user_scoped_grants_are_intersected_per_repo():
    """父只管 acme/api,子用户不能借着角色把自己铺到 acme/web。"""
    parent = frozenset()
    parent_scoped = {"changes.approve": frozenset({"github-acme-api"})}
    perms, scoped = effective_permissions(
        ["changes.approve@github-acme-api", "changes.approve@github-acme-web"],
        [],
        parent=parent,
        parent_scoped=parent_scoped,
    )
    assert perms == frozenset()
    assert scoped == {"changes.approve": frozenset({"github-acme-api"})}


def test_a_project_scoped_grant_covers_every_repo_under_it():
    """授在项目上 = 项目下每一个仓库,包括登录之后才加进来的那个。

    所以这一档不能在建身份时展开成一份仓库清单:新仓库进来时没有人回来改
    这份身份,展开的那一份会漏掉它。判定时带上项目问一次(Identity.allows 的
    project 参数)才对得上。
    """
    perms, scoped = effective_permissions(["changes.approve@acme"], [])
    assert perms == frozenset()
    assert scoped == {"changes.approve": frozenset({"acme"})}

    identity = Identity(
        user_id="u", name="n", tenant="t", permissions=perms, scoped_permissions=scoped
    )
    # 项目下的仓库都算数
    assert identity.allows("changes.approve", "github-acme-api", "acme")
    # 项目外的仓库不算,即使它恰好也叫 acme-api
    assert not identity.allows("changes.approve", "github-other-api", "other")
    # 不点名仓库也不点名项目 = 整个工作区,不该放行
    assert not identity.allows("changes.approve", None, None)
    # 只点名项目(覆盖整个项目的动作)算数 —— 项目档就是那一档的边界
    assert identity.allows("changes.approve", None, "acme")
    # 项目外的那一档不算
    assert not identity.allows("changes.approve", None, "other")


def test_repo_and_project_grants_do_not_leak_across():
    """项目与仓库共用 projects 的一个名字空间,两条授权各管各的。"""
    perms, scoped = effective_permissions(
        ["changes.approve@acme", "changes.approve@github-other-api"], []
    )
    identity = Identity(
        user_id="u", name="n", tenant="t", permissions=perms, scoped_permissions=scoped
    )
    # 仓库授权只管那一个仓库:它所在的 project 是 other,照样算数
    assert identity.allows("changes.approve", "github-other-api", "other")
    # 项目授权覆盖 acme 下每一个仓库,与 other 无关
    assert identity.allows("changes.approve", "github-acme-web", "acme")
    # 两条授权都没点名的仓库,不因为项目这一档没写它就放行
    assert not identity.allows("changes.approve", "github-other-web", "other")


def test_read_permissions_are_not_writes():
    assert not is_write_permission("changes.read")
    assert not is_write_permission("audit.read")
    assert is_write_permission("changes.approve")
    assert is_write_permission("settings.write")
    assert is_write_permission("users.manage")


def test_admin_keeps_valid_scoped_grants_and_drops_the_rest():
    """写错的收窄丢掉而不是猜:猜成工作区级会多给。"""
    from engine.auth.admin import _clean_permissions

    assert _clean_permissions(
        [
            "changes.read",
            "changes.approve@github-acme-api",
            "users.manage@github-acme-api",  # 收窄不了的权限
            "changes.approve@",  # 没说收窄到哪
            "made.up@github-acme-api",  # 不存在的权限
        ]
    ) == ["changes.approve@github-acme-api", "changes.read"]
