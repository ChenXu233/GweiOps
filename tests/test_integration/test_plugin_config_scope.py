# tests/test_integration/test_plugin_config_scope.py
"""插件声明的配置项,平台要真读得出来 —— 不需要先在 Settings 里登记。"""

from __future__ import annotations

import pytest

from engine.shared.config import config


def _register(name: str, prefix: str, required=None, optional=None) -> None:
    config.register_scope(name=name, prefix=prefix, required=required or [], optional=optional or [])


@pytest.fixture
def clean_scopes():
    before = set(config._scopes)
    yield
    for name in list(config._scopes):
        if name not in before:
            config._scopes.pop(name, None)


def test_a_field_only_the_plugin_declared_is_read_from_the_environment(
    monkeypatch, clean_scopes
):
    """插件声明了 api_key,平台上根本没有这个名字的 Settings 字段 —— 照样要读得到。"""
    monkeypatch.setenv("ACME_BOT_API_KEY", "sk-from-env")
    _register("acme-bot-env", "ACME_BOT_", required=["api_key"])

    assert config.get_scope_config("acme-bot-env")["api_key"] == "sk-from-env"
    assert config.validate_scope("acme-bot-env") == []


def test_a_value_can_come_from_the_dotenv_file(tmp_path, monkeypatch, clean_scopes):
    path = tmp_path / ".env"
    path.write_text("ACME_EDGE_TOKEN=tok-from-file\n", encoding="utf-8")
    monkeypatch.setitem(config.settings.model_config, "env_file", str(path))
    monkeypatch.delenv("ACME_EDGE_TOKEN", raising=False)
    _register("acme-edge", "ACME_EDGE_", required=["token"])

    assert config.get_scope_config("acme-edge")["token"] == "tok-from-file"


def test_a_missing_required_field_is_named_the_way_you_would_set_it(
    monkeypatch, clean_scopes
):
    monkeypatch.delenv("ACME_GHOST_SECRET", raising=False)
    _register("acme-ghost", "ACME_GHOST_", required=["secret"])

    assert config.validate_scope("acme-ghost") == ["ACME_GHOST_SECRET"]
    assert config.get_scope_config("acme-ghost") == {}


def test_optional_fields_come_back_when_present(monkeypatch, clean_scopes):
    monkeypatch.setenv("ACME_OPT_BASE_URL", "https://x")
    monkeypatch.delenv("ACME_OPT_TOKEN", raising=False)
    _register("acme-opt", "ACME_OPT_", required=[], optional=["token", "base_url"])

    assert config.get_scope_config("acme-opt") == {"base_url": "https://x"}


def test_an_unknown_scope_is_a_loud_error(clean_scopes):
    with pytest.raises(KeyError):
        config.get_scope_config("no-such-scope")


def test_a_declared_settings_field_still_wins(monkeypatch, clean_scopes):
    """部署把字段写进了 Settings 时以它为准,别让环境变量把它盖掉。"""
    monkeypatch.setattr(config.settings, "github_app_app_id", "12345", raising=False)
    _register("acme-settings", "GITHUB_APP_", optional=["app_id"])

    assert config.get_scope_config("acme-settings")["app_id"] == "12345"
