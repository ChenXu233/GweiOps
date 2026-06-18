# tests/test_webhook.py
import json
import hashlib
import hmac
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from src.main import app


def make_github_signature(secret: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


@pytest.mark.asyncio
async def test_webhook_issues_opened(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test_secret")

    payload = json.dumps({
        "action": "opened",
        "issue": {"number": 1, "title": "Test bug", "body": "Something is broken"},
        "repository": {"full_name": "owner/repo", "id": 12345, "clone_url": "https://github.com/owner/repo.git"},
    }).encode()

    signature = make_github_signature("test_secret", payload)

    with patch("src.services.webhook.process_issue_event", new_callable=AsyncMock) as mock_process:
        mock_process.return_value = {"status": "ok"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/webhook/github",
                content=payload,
                headers={
                    "X-GitHub-Event": "issues",
                    "X-Hub-Signature-256": signature,
                    "Content-Type": "application/json",
                    "X-GitHub-Delivery": "test-delivery-123",
                },
            )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_webhook_missing_signature():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhook/github",
            content=b"{}",
            headers={"X-GitHub-Event": "issues"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_webhook_invalid_signature(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test_secret")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhook/github",
            content=b"{}",
            headers={"X-GitHub-Event": "issues", "X-Hub-Signature-256": "sha256=invalid"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_health_check():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_webhook_ping_event():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhook/github",
            content=b"{}",
            headers={"X-GitHub-Event": "ping"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "pong"
