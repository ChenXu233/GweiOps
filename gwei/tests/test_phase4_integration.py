# tests/test_phase4_integration.py
import pytest
from src.services.pr_creator import PRCreator, PRResult
from src.services.voting import VotingService, VoteStatus
from src.services.pr_webhook import analyze_pr_changes


def test_full_pr_flow():
    """测试完整的 PR 流程：分析 -> 创建 -> 投票 -> 合并。"""
    # 1. 分析 PR 修改
    files = [
        {"filename": "src/parser.py", "changes": 50, "additions": 30, "deletions": 20},
        {"filename": "tests/test_parser.py", "changes": 20, "additions": 15, "deletions": 5},
    ]

    analysis = analyze_pr_changes(files)
    assert analysis["risk_score"] > 0
    assert analysis["min_approvals"] >= 1

    # 2. 创建 PR 结果
    pr_result = PRResult(
        success=True,
        pr_number=42,
        pr_url="https://github.com/test/repo/pull/42",
        error=None,
    )
    assert pr_result.success is True

    # 3. 投票流程
    voting = VotingService(min_approvals=analysis["min_approvals"])

    # 添加投票
    for i in range(analysis["min_approvals"]):
        result = voting.add_vote(
            pr_id=42,
            voter_id=i + 1,
            voter_role="collaborator",
            vote="approve",
        )
        assert result.success is True

    # 检查状态
    status = voting.get_status(pr_id=42)
    assert status.approvals == analysis["min_approvals"]
    assert status.is_approved is True


def test_pr_risk_analysis():
    """测试 PR 风险分析。"""
    # 低风险
    low_risk_files = [
        {"filename": "README.md", "changes": 10, "additions": 5, "deletions": 5},
    ]
    low_risk = analyze_pr_changes(low_risk_files)
    assert low_risk["risk_score"] < 30
    assert low_risk["min_approvals"] == 1

    # 高风险
    high_risk_files = [
        {"filename": "src/parser/core.py", "changes": 200, "additions": 100, "deletions": 100},
        {"filename": "src/lexer/tokenizer.py", "changes": 150, "additions": 80, "deletions": 70},
    ]
    high_risk = analyze_pr_changes(high_risk_files)
    assert high_risk["risk_score"] >= 60
    assert high_risk["min_approvals"] == 3


def test_voting_with_owner_override():
    """测试 Owner 覆盖投票。"""
    voting = VotingService(min_approvals=3, owner_can_override=True)

    # Owner 单人投票
    voting.add_vote(pr_id=1, voter_id=1, voter_role="owner", vote="approve")

    status = voting.get_status(pr_id=1)
    assert status.is_approved is True


def test_voting_rejection():
    """测试投票拒绝。"""
    voting = VotingService(min_approvals=2)

    voting.add_vote(pr_id=1, voter_id=1, voter_role="collaborator", vote="approve")
    voting.add_vote(pr_id=1, voter_id=2, voter_role="collaborator", vote="reject")

    status = voting.get_status(pr_id=1)
    assert status.approvals == 1
    assert status.rejections == 1
    assert status.is_approved is False
