# tests/test_reproducer.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.services.reproducer import BugReproducer, ReproductionResult


@pytest.mark.asyncio
async def test_reproducer_init():
    reproducer = BugReproducer()
    assert reproducer is not None


@pytest.mark.asyncio
async def test_reproduce_success():
    reproducer = BugReproducer()

    with patch.object(reproducer, "_clone_repo", new_callable=AsyncMock) as mock_clone:
        with patch.object(reproducer, "_run_reproduction", new_callable=AsyncMock) as mock_run:
            mock_clone.return_value = True
            mock_run.return_value = ReproductionResult(
                success=True,
                error_output="TypeError: Cannot read property 'x' of null",
                stack_trace="at parse (parser.js:42:15)",
            )

            result = await reproducer.reproduce(
                repo_url="https://github.com/test/repo.git",
                issue_number=1,
                steps=["npm install", "node parser.js null"],
            )

            assert result.success is True
            assert "TypeError" in result.error_output


@pytest.mark.asyncio
async def test_reproduce_failure():
    reproducer = BugReproducer()

    with patch.object(reproducer, "_clone_repo", new_callable=AsyncMock) as mock_clone:
        mock_clone.return_value = False

        result = await reproducer.reproduce(
            repo_url="https://github.com/test/nonexistent.git",
            issue_number=1,
            steps=["npm install"],
        )

        assert result.success is False
        assert result.error is not None


@pytest.mark.asyncio
async def test_reproduce_timeout():
    reproducer = BugReproducer(timeout=1)

    with patch.object(reproducer, "_clone_repo", new_callable=AsyncMock) as mock_clone:
        with patch.object(reproducer, "_run_reproduction", new_callable=AsyncMock) as mock_run:
            mock_clone.return_value = True
            mock_run.side_effect = TimeoutError("Reproduction timed out")

            result = await reproducer.reproduce(
                repo_url="https://github.com/test/repo.git",
                issue_number=1,
                steps=["sleep 100"],
            )

            assert result.success is False
            assert "timeout" in result.error.lower()


def test_reproduction_result_success():
    result = ReproductionResult(
        success=True,
        error_output="Error message",
        stack_trace="at line 42",
    )

    assert result.success is True
    assert result.error_output == "Error message"


def test_reproduction_result_failure():
    result = ReproductionResult(
        success=False,
        error="Clone failed",
    )

    assert result.success is False
    assert result.error == "Clone failed"
