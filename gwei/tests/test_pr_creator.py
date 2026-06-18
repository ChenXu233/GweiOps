# tests/test_pr_creator.py
import pytest
from unittest.mock import AsyncMock, patch
from src.services.pr_creator import PRCreator, PRResult


@pytest.mark.asyncio
async def test_create_pr():
    creator = PRCreator()

    with patch.object(creator.github, "create_pr", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = {
            "number": 42,
            "url": "https://github.com/test/repo/pull/42",
            "title": "Fix: Parser crash",
        }

        result = await creator.create(
            repo="test/repo",
            title="Fix: Parser crash",
            body="Fixes #1",
            head="fix/parser-crash",
            base="main",
        )

        assert result.success is True
        assert result.pr_number == 42
        assert "42" in result.pr_url


@pytest.mark.asyncio
async def test_create_pr_failure():
    creator = PRCreator()

    with patch.object(creator.github, "create_pr", new_callable=AsyncMock) as mock_create:
        mock_create.side_effect = Exception("API error")

        result = await creator.create(
            repo="test/repo",
            title="Fix: Parser crash",
            body="Fixes #1",
            head="fix/parser-crash",
            base="main",
        )

        assert result.success is False
        assert result.error is not None


def test_pr_result_success():
    result = PRResult(
        success=True,
        pr_number=42,
        pr_url="https://github.com/test/repo/pull/42",
        error=None,
    )

    assert result.success is True
    assert result.pr_number == 42


def test_pr_result_failure():
    result = PRResult(
        success=False,
        pr_number=None,
        pr_url=None,
        error="API error",
    )

    assert result.success is False
    assert result.error == "API error"


@pytest.mark.asyncio
async def test_create_pr_with_labels():
    creator = PRCreator()

    with patch.object(creator.github, "create_pr", new_callable=AsyncMock) as mock_create:
        with patch.object(creator.github, "add_labels", new_callable=AsyncMock) as mock_labels:
            mock_create.return_value = {
                "number": 42,
                "url": "https://github.com/test/repo/pull/42",
                "title": "Fix: Parser crash",
            }
            mock_labels.return_value = {"labels": ["ai-generated"]}

            result = await creator.create(
                repo="test/repo",
                title="Fix: Parser crash",
                body="Fixes #1",
                head="fix/parser-crash",
                base="main",
                labels=["ai-generated"],
            )

            assert result.success is True
            mock_labels.assert_called_once()
