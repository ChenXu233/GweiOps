# tests/test_integration/test_registration_policy.py
"""注册策略、验证码与配额限量:不碰库的那一半。"""

from __future__ import annotations

import pytest

from engine.auth import registration as policy_mod
from engine.quota import QuotaError, limits_for, parse_limit
from engine.shared.config import config


@pytest.fixture(autouse=True)
def _clean_config(monkeypatch):
    """每个用例从"注册关着、只有邮箱"开始,并清掉库里的覆盖。"""
    monkeypatch.setattr(config.settings, "registration_enabled", False)
    monkeypatch.setattr(config.settings, "registration_methods", "email")
    monkeypatch.setattr(config.settings, "registration_requires_verification", True)
    monkeypatch.setattr(config.settings, "registration_test_code", "")
    monkeypatch.setattr(config.settings, "oidc_issuer", "")
    monkeypatch.setattr(config.settings, "oidc_client_id", "")
    monkeypatch.setattr(config.settings, "oidc_client_secret", "")
    config.apply_stored({})
    policy_mod.rate_forget("a@example.com")
    yield
    config.apply_stored({})


def test_registration_is_off_by_default():
    # 一台已经跑起来的实例,不该因为升级就开始接受陌生人
    assert policy_mod.policy_for("").enabled is False


def test_methods_are_parsed_and_deduped(monkeypatch):
    monkeypatch.setattr(config.settings, "registration_enabled", True)
    monkeypatch.setattr(config.settings, "registration_methods", "email, phone ,email,sms")
    policy = policy_mod.policy_for("")
    # sms 不是一种注册方式:手机号是 phone;写错的方法不猜,直接丢掉
    assert policy.methods == ("email", "phone")
    assert policy.allows("email")


def test_oidc_only_shows_up_when_it_is_configured(monkeypatch):
    monkeypatch.setattr(config.settings, "registration_enabled", True)
    monkeypatch.setattr(config.settings, "registration_methods", "email,oidc")
    assert "oidc" not in policy_mod.policy_for("").methods

    monkeypatch.setattr(config.settings, "oidc_issuer", "https://id.example.com")
    monkeypatch.setattr(config.settings, "oidc_client_id", "client")
    monkeypatch.setattr(config.settings, "oidc_client_secret", "secret")
    assert "oidc" in policy_mod.policy_for("").methods


def test_tenant_overrides_one_key_without_copying_the_rest(monkeypatch):
    monkeypatch.setattr(config.settings, "registration_enabled", False)
    # 公共那份:所有租户都能读到,所以租户为空时按它算
    config.apply_stored({"": {"registration": {"registration_enabled": "true"}}})
    assert policy_mod.policy_for("").enabled is True
    # 逐键覆盖:没写的那些还是全局值
    assert policy_mod.policy_for("").requires_verification is True
    # 租户自己那份也读得到,并且租户值优先
    config.apply_stored(
        {
            "": {"registration": {"registration_enabled": "true"}},
            "acme": {"registration": {"registration_enabled": "false"}},
        }
    )
    assert policy_mod.policy_for("acme").enabled is False


def test_code_hash_is_bound_to_target_and_purpose():
    left = policy_mod.hash_code("a@example.com", "register", "123456")
    assert left != policy_mod.hash_code("b@example.com", "register", "123456")
    assert left != policy_mod.hash_code("a@example.com", "reset", "123456")


def test_rate_limit_counts_and_resets(monkeypatch):
    monkeypatch.setattr(config.settings, "registration_rate_limit", 2)
    policy = policy_mod.policy_for("")
    target = "a@example.com"
    assert policy_mod.rate_allows(target, policy)
    policy_mod.rate_record(target)
    policy_mod.rate_record(target)
    assert not policy_mod.rate_allows(target, policy)
    policy_mod.rate_forget(target)
    assert policy_mod.rate_allows(target, policy)


def test_rate_limit_of_zero_means_no_limit(monkeypatch):
    monkeypatch.setattr(config.settings, "registration_rate_limit", 0)
    policy = policy_mod.policy_for("")
    for _ in range(50):
        policy_mod.rate_record("a@example.com")
    assert policy_mod.rate_allows("a@example.com", policy)


# ---------------------------------------------------------------------------
# 配额
# ---------------------------------------------------------------------------


def test_limit_parsing():
    limit = parse_limit("issues", "2000/30d")
    assert (limit.amount, limit.window_hours) == (2000, 720)
    assert parse_limit("issues", "100/5h").window_hours == 5
    assert parse_limit("issues", "10/2w").window_hours == 336


def test_empty_limit_means_unlimited():
    limit = parse_limit("issues", "")
    assert limit.window_hours == 0
    assert limit.window() is None


def test_a_written_wrong_limit_is_refused_not_ignored():
    # 写错的限量不能悄悄当成"不限" —— 那等于把限额关掉却没人知道
    with pytest.raises(QuotaError):
        parse_limit("issues", "2000")
    with pytest.raises(QuotaError):
        parse_limit("issues", "两千/30d")
    with pytest.raises(QuotaError):
        parse_limit("issues", "2000/30y")


def test_tenant_limit_overrides_the_platform_default():
    config.apply_stored({"": {"quota": {"issues": "10/30d"}}})
    assert limits_for("").get("issues").amount == 10
    config.apply_stored({"acme": {"quota": {"issues": "1/30d"}}})
    assert limits_for("acme").get("issues").amount == 1
