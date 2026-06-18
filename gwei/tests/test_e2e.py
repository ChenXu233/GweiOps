# tests/test_e2e.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.services.labeler import LabelGenerator
from src.services.completeness import CompletenessChecker
from src.services.duplicate_detector import DuplicateDetector
from src.services.code_analyzer import CodeAnalyzer
from src.services.patch_generator import PatchGenerator
from src.services.pr_creator import PRCreator, PRResult
from src.services.voting import VotingService
from src.services.code_reviewer import CodeReviewer
from src.services.review_report import ReviewReportGenerator


def test_full_issue_to_pr_flow():
    """完整的 Issue -> 分析 -> Patch -> PR 流程。"""
    # 初始化所有服务
    labeler = LabelGenerator()
    completeness = CompletenessChecker()
    duplicate_detector = DuplicateDetector()
    code_analyzer = CodeAnalyzer()
    patch_generator = PatchGenerator()
    pr_creator = PRCreator()
    voting = VotingService(min_approvals=2)
    code_reviewer = CodeReviewer()
    report_generator = ReviewReportGenerator()

    # 1. 接收 Issue
    issue_title = "Parser crash on null input"
    issue_body = """
## 复现步骤
1. 调用 parser.parse(null)
2. 观察崩溃

## 期望行为
应该抛出明确的错误信息

## 实际行为
应用崩溃，显示 segfault 错误
"""

    # 2. 生成标签
    labels = labeler.generate(title=issue_title, body=issue_body)
    assert "parser" in labels
    assert "bug" in labels

    # 3. 检查完整性
    completeness_report = completeness.check(issue_body)
    assert completeness_report.is_complete is True

    # 4. 检查重复
    dup_result = duplicate_detector.detect(
        title=issue_title,
        body=issue_body,
        existing_issues=[],
    )
    assert dup_result.is_duplicate is False

    # 5. 分析代码
    code = """
def parse(input):
    return input.split()
"""
    analysis = code_analyzer.analyze(code, language="python")
    assert "parse" in analysis.functions

    # 6. 生成 Patch
    patches = patch_generator.generate_all(
        issue_title=issue_title,
        issue_body=issue_body,
        file_path="src/parser.py",
    )
    assert len(patches) == 3

    # 7. 代码审查
    review_result = code_reviewer.review(code, language="python")
    review_report = report_generator.generate(review_result)
    assert "代码审查" in review_report

    # 8. 模拟创建 PR
    # (实际需要 GitHub API，这里只验证流程)

    # 9. 投票流程
    voting.add_vote(pr_id=1, voter_id=1, voter_role="collaborator", vote="approve")
    voting.add_vote(pr_id=1, voter_id=2, voter_role="collaborator", vote="approve")

    status = voting.get_status(pr_id=1)
    assert status.is_approved is True


def test_incomplete_issue_flow():
    """不完整的 Issue 应该被拒绝。"""
    labeler = LabelGenerator()
    completeness = CompletenessChecker()

    issue_title = "Something is broken"
    issue_body = "It doesn't work"

    # 生成标签
    labels = labeler.generate(title=issue_title, body=issue_body)

    # 检查完整性
    report = completeness.check(issue_body)
    assert report.is_complete is False
    assert len(report.missing_fields) > 0


def test_duplicate_issue_flow():
    """重复的 Issue 应该被检测。"""
    duplicate_detector = DuplicateDetector(threshold=0.7)

    existing_issues = [
        {"id": 1, "title": "Parser crash on null", "body": "Parser crashes when input is null"},
    ]

    # 检测重复
    result = duplicate_detector.detect(
        title="Parser crash on null input",
        body="The parser crashes when input is null",
        existing_issues=existing_issues,
    )

    assert result.score > 0.5


def test_voting_rejection_flow():
    """投票拒绝流程。"""
    voting = VotingService(min_approvals=2)

    # 添加投票
    voting.add_vote(pr_id=1, voter_id=1, voter_role="collaborator", vote="approve")
    voting.add_vote(pr_id=1, voter_id=2, voter_role="collaborator", vote="reject")

    status = voting.get_status(pr_id=1)
    assert status.approvals == 1
    assert status.rejections == 1
    assert status.is_approved is False


def test_code_review_flow():
    """代码审查流程。"""
    reviewer = CodeReviewer()
    report_generator = ReviewReportGenerator()

    code = """
import os
import sys

try:
    pass
except:
    pass

def add(a, b):
    return a + b
"""

    # 审查代码
    result = reviewer.review(code, language="python")
    assert len(result.issues) > 0

    # 生成报告
    report = report_generator.generate(result)
    assert "代码审查" in report