# tests/test_integration/test_identity_model.py
"""人是全局的,角色是工作区给的 —— 拆表之后那几条判据。

这些用例不碰库(表结构与读路径由门控用例覆盖),验的是纯逻辑:路径怎么选工作区、
不带工作区时按什么挑、以及"空字符串与 None 不是一回事"这条容易写错的地方。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from engine.api.auth import (
    Actor,
    workspace_access,
    workspace_of,
)


class _Url:
    def __init__(self, path: str) -> None:
        self.path = path


class _Request:
    """够用的请求替身:工作区只从 path 来,身份只从 scope 来。"""

    def __init__(self, path: str, actor: Actor | None = None) -> None:
        self.url = _Url(path)
        self.scope = {"actor": actor} if actor is not None else {}


def _actor(tenant: str) -> Actor:
    return Actor(token_id="t", name="值班人", tenant=tenant, scope="operate", static=True)


def test_the_workspace_comes_from_the_path():
    assert workspace_of(_Request("/api/workspaces/acme/issues")) == "acme"
    # 门牌本身也是工作区:同一段字符在两个位置上是两件事
    assert workspace_of(_Request("/api/workspaces/acme")) == "acme"
    # 没写工作区段就是空:老接口与机器令牌都走这条
    assert workspace_of(_Request("/api/issues")) == ""


def test_a_member_sees_the_workspace_in_the_path():
    request = _Request("/api/workspaces/acme/issues", _actor("acme"))
    request.scope["_workspace_path"] = "/api/workspaces/acme/issues"
    assert workspace_access(request) == "acme"


def test_asking_for_a_workspace_you_do_not_belong_to_is_403_and_names_it():
    """不替他"落回他有权限的那一个":静默换位会让"我点了 Acme 却看到 Beta"变成常态。"""
    request = _Request("/api/workspaces/other/issues", _actor("acme"))
    request.scope["_workspace_path"] = "/api/workspaces/other/issues"
    with pytest.raises(HTTPException) as caught:
        workspace_access(request)
    assert caught.value.status_code == 403
    assert "other" in caught.value.detail


def test_without_a_segment_the_token_decides():
    assert workspace_access(_Request("/api/issues", _actor("acme"))) == "acme"


def test_a_cross_tenant_token_is_none_not_empty_string():
    """`*` 令牌看得见全部。把它写成空串,账本会按空租户去筛,一行都读不出来。"""
    wildcard = Actor(token_id="t", name="维护者", tenant="", scope="operate", static=True)
    assert workspace_access(_Request("/api/issues", wildcard)) is None
    # 没配鉴权的部署同一个道理
    assert workspace_access(_Request("/api/issues")) is None


def test_the_identity_carries_the_person_and_the_membership_apart():
    """`user_id` 是成员关系的 id,`person_id` 才是那个人 —— 会话挂在后者上。"""
    from engine.auth import Identity

    identity = Identity(
        user_id="membership-in-acme",
        name="春风和煦",
        tenant="acme",
        permissions=frozenset({"changes.read"}),
        person_id="person-1",
        person_email="a@example.com",
        membership_id="membership-in-acme",
    )
    assert identity.person_id != identity.user_id
    assert identity.has("changes.read")
    assert not identity.has("users.manage")


def test_a_password_is_one_per_person_not_one_per_workspace():
    """人是全局的:凭据挂人,成员关系挂角色。拆表买到的就是这一条。"""
    from engine.db.models import Membership, Person

    assert "password_hash" in Person.__table__.columns
    assert "password_hash" not in Membership.__table__.columns
    assert "tenant_id" in Membership.__table__.columns
    assert "email" in Person.__table__.columns
    # 会话属于人,不属于"某个工作区里的那个人"
    from engine.db.models import UserSession

    columns = set(UserSession.__table__.columns.keys())
    assert "person_id" in columns
    assert "user_id" not in columns
