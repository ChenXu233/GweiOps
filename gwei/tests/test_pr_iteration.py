# tests/test_pr_iteration.py
import pytest
from unittest.mock import AsyncMock, patch
from src.services.pr_iteration import PRIterationService, IterationResult


@pytest.mark.asyncio
async def test_iteration_service_init():
    service = PRIterationService()
    assert service is not None


@pytest.mark.asyncio
async def test_process_review_comment():
    service = PRIterationService()

    with patch.object(service, "_analyze_comment", new_callable=AsyncMock) as mock_analyze:
        with patch.object(service, "_generate_fix", new_callable=AsyncMock) as mock_fix:
            mock_analyze.return_value = {
                "type": "request_changes",
                "issues": ["Missing error handling"],
            }
            mock_fix.return_value = {
                "diff": "--- a/file.py\n+++ b/file.py\n+try:\n+    pass\n+except:\n+    pass",
                "description": "Added error handling",
            }

            result = await service.process_review_comment(
                pr_number=1,
                comment_body="Please add error handling",
                commenter="reviewer",
            )

            assert result.success is True
            assert result.action == "update_pr"


@pytest.mark.asyncio
async def test_process_question_comment():
    service = PRIterationService()

    with patch.object(service, "_analyze_comment", new_callable=AsyncMock) as mock_analyze:
        with patch.object(service, "_generate_response", new_callable=AsyncMock) as mock_response:
            mock_analyze.return_value = {
                "type": "question",
                "question": "Why did you choose this approach?",
            }
            mock_response.return_value = "I chose this approach because..."

            result = await service.process_review_comment(
                pr_number=1,
                comment_body="Why did you choose this approach?",
                commenter="reviewer",
            )

            assert result.success is True
            assert result.action == "reply"


@pytest.mark.asyncio
async def test_process_approve_comment():
    service = PRIterationService()

    with patch.object(service, "_analyze_comment", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.return_value = {
            "type": "approve",
        }

        result = await service.process_review_comment(
            pr_number=1,
            comment_body="LGTM!",
            commenter="reviewer",
        )

        assert result.success is True
        assert result.action == "none"


def test_iteration_result_success():
    result = IterationResult(
        success=True,
        action="update_pr",
        message="Updated PR with fixes",
    )

    assert result.success is True
    assert result.action == "update_pr"


def test_iteration_result_reply():
    result = IterationResult(
        success=True,
        action="reply",
        message="Explanation text",
    )

    assert result.success is True
    assert result.action == "reply"
