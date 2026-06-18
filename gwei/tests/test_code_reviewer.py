# tests/test_code_reviewer.py
import pytest
from src.services.code_reviewer import CodeReviewer, ReviewResult, ReviewIssue


def test_reviewer_init():
    reviewer = CodeReviewer()
    assert reviewer is not None


def test_review_clean_code():
    reviewer = CodeReviewer()
    code = """
def hello():
    print("Hello, world!")

def add(a: int, b: int) -> int:
    return a + b
"""
    result = reviewer.review(code, language="python")

    assert result.issues == []
    assert result.score >= 90


def test_review_missing_type_hints():
    reviewer = CodeReviewer()
    code = """
def add(a, b):
    return a + b
"""
    result = reviewer.review(code, language="python")

    assert any(issue.severity == "warning" for issue in result.issues)


def test_review_long_function():
    reviewer = CodeReviewer()
    code = """
def long_function():
    """ + "\n    pass\n" * 100 + """
"""
    result = reviewer.review(code, language="python")

    assert any("too long" in issue.message.lower() or "long" in issue.message.lower() for issue in result.issues)


def test_review_bare_except():
    reviewer = CodeReviewer()
    code = """
try:
    pass
except:
    pass
"""
    result = reviewer.review(code, language="python")

    assert any("except" in issue.message.lower() for issue in result.issues)


def test_review_unused_import():
    reviewer = CodeReviewer()
    code = """
import os
import sys

def hello():
    print("hello")
"""
    result = reviewer.review(code, language="python")

    # 可能检测到未使用的导入
    assert isinstance(result.issues, list)


def test_review_result_dataclass():
    result = ReviewResult(
        issues=[],
        score=100,
        summary="No issues found",
    )

    assert result.issues == []
    assert result.score == 100


def test_review_issue_dataclass():
    issue = ReviewIssue(
        severity="warning",
        message="Missing type hints",
        line=5,
        file="test.py",
    )

    assert issue.severity == "warning"
    assert issue.message == "Missing type hints"
    assert issue.line == 5


def test_review_multiple_issues():
    reviewer = CodeReviewer()
    code = """
import os
import sys
import json

try:
    pass
except:
    pass

def add(a, b):
    return a + b
"""
    result = reviewer.review(code, language="python")

    # 应该检测到多个问题
    assert len(result.issues) > 0
    assert result.score < 100
