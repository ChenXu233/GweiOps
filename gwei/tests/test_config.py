# tests/test_config.py
import os
from src.config import Settings


def test_settings_defaults():
    """默认配置值"""
    settings = Settings()
    assert settings.app_name == "gwei"
    assert settings.debug is False
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.redis_url == "redis://localhost:6379/0"


def test_settings_from_env(monkeypatch):
    """从环境变量加载配置"""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/testdb")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/1")
    monkeypatch.setenv("DEBUG", "true")

    settings = Settings()
    assert settings.database_url == "postgresql+asyncpg://user:pass@localhost:5432/testdb"
    assert settings.redis_url == "redis://redis:6379/1"
    assert settings.debug is True


def test_github_app_settings(monkeypatch):
    """GitHub App 配置"""
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_PRIVATE_KEY", "-----BEGIN RSA PRIVATE KEY-----")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "whsec_test")

    settings = Settings()
    assert settings.github_app_id == "12345"
    assert settings.github_private_key == "-----BEGIN RSA PRIVATE KEY-----"
    assert settings.github_webhook_secret == "whsec_test"
