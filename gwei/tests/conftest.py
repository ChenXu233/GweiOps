# tests/conftest.py
import pytest
from src.config import Settings


@pytest.fixture
def settings():
    return Settings()


@pytest.fixture
def test_settings(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/testdb")
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_PRIVATE_KEY", "test-key")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "whsec_test_secret")
    return Settings()
