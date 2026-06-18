# tests/test_pr_webhook.py
import pytest
from unittest.mock import AsyncMock, patch
from src.services.pr_webhook import process_pr_event, process_comment_event


@pytest.mark.asyncio
async def test_process_pr_opened():
    payload = {
        "action": "opened",
        "pull_request": {
            "number": 1,
            "title": "Fix: Parser crash",
            "body": "Fixes #42",
            "head": {"ref": "fix/parser-crash"},
            "base": {"ref": "main"},
        },
        "repository": {"full_name": "test/repo"},
    }

    with patch("src.services.pr_webhook.analyze_pr_changes", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.return_value = {
            "risk_score": 30,
            "min_approvals": 2,
            "core_changes": False,
        }

        result = await process_pr_event(payload)

        assert result["status"] == "ok"
        assert result["action"] == "opened"


@pytest.mark.asyncio
async def test_process_pr_synchronize():
    payload = {
        "action": "synchronize",
        "pull_request": {
            "number": 1,
            "title": "Fix: Parser crash",
        },
        "repository": {"full_name": "test/repo"},
    }

    result = await process_pr_event(payload)
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_process_comment_vote():
    payload = {
        "action": "created",
        "comment": {
            "body": "同意",
            "user": {"id": 42, "login": "collaborator"},
        },
        "issue": {
            "number": 1,
            "pull_request": {"url": "https://api.github.com/repos/test/repo/pulls/1"},
        },
        "repository": {"full_name": "test/repo"},
    }

    with patch("src.services.pr_webhook.process_vote", new_callable=AsyncMock) as mock_vote:
        mock_vote.return_value = {"success": True, "message": "Vote recorded"}

        result = await process_comment_event(payload)

        assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_process_comment_not_vote():
    payload = {
        "action": "created",
        "comment": {
            "body": "This looks good, but please add more tests.",
            "user": {"id": 42, "login": "reviewer"},
        },
        "issue": {
            "number": 1,
        },
        "repository": {"full_name": "test/repo"},
    }

    result = await process_comment_event(payload)
    assert result["status"] == "ok"


def test_analyze_pr_changes():
    from src.services.pr_webhook import analyze_pr_changes

    files = [
        {"filename": "src/parser.py", "changes": 50, "additions": 30, "deletions": 20},
        {"filename": "tests/test_parser.py", "changes": 20, "additions": 15, "deletions": 5},
    ]

    result = analyze_pr_changes(files)

    assert "risk_score" in result
    assert "min_approvals" in result
    assert isinstance(result["risk_score"], int)
