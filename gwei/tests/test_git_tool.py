# tests/test_git_tool.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.services.git_tool import GitTool, GitResult


def test_git_result_success():
    result = GitResult(success=True, output="commit abc123", error=None)
    assert result.success is True
    assert result.output == "commit abc123"
    assert result.error is None


def test_git_result_failure():
    result = GitResult(success=False, output="", error="fatal: not a git repository")
    assert result.success is False
    assert result.error == "fatal: not a git repository"


@pytest.mark.asyncio
async def test_clone_repository():
    tool = GitTool()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        process = AsyncMock()
        process.communicate.return_value = (b"Cloning into 'repo'...", b"")
        process.returncode = 0
        mock_exec.return_value = process

        result = await tool.clone("https://github.com/test/repo.git", "/tmp/repo")

        assert result.success is True
        assert "clone" in str(mock_exec.call_args)


@pytest.mark.asyncio
async def test_checkout_branch():
    tool = GitTool()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        process = AsyncMock()
        process.communicate.return_value = (b"Switched to branch 'fix-123'", b"")
        process.returncode = 0
        mock_exec.return_value = process

        result = await tool.checkout("/tmp/repo", "fix-123")

        assert result.success is True


@pytest.mark.asyncio
async def test_create_branch():
    tool = GitTool()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        process = AsyncMock()
        process.communicate.return_value = (b"", b"")
        process.returncode = 0
        mock_exec.return_value = process

        result = await tool.create_branch("/tmp/repo", "fix-123")

        assert result.success is True


@pytest.mark.asyncio
async def test_commit_changes():
    tool = GitTool()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        process = AsyncMock()
        process.communicate.return_value = (b"[fix-123 abc1234] Fix bug", b"")
        process.returncode = 0
        mock_exec.return_value = process

        result = await tool.commit("/tmp/repo", "Fix bug")

        assert result.success is True


@pytest.mark.asyncio
async def test_clone_failure():
    tool = GitTool()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
        process = AsyncMock()
        process.communicate.return_value = (b"", b"fatal: repository not found")
        process.returncode = 128
        mock_exec.return_value = process

        result = await tool.clone("https://github.com/test/nonexistent.git", "/tmp/repo")

        assert result.success is False
        assert "not found" in result.error
