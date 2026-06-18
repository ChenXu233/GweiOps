# tests/test_phase5_integration.py
import pytest
from src.services.code_reviewer import CodeReviewer, ReviewResult
from src.services.review_report import ReviewReportGenerator


def test_full_review_flow():
    """测试完整的代码审查流程：审查 -> 生成报告。"""
    reviewer = CodeReviewer()
    report_generator = ReviewReportGenerator()

    # 有问题的代码
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

    # 1. 审查代码
    result = reviewer.review(code, language="python")

    assert len(result.issues) > 0
    assert result.score < 100

    # 2. 生成报告
    report = report_generator.generate(result)

    assert "代码审查" in report
    assert str(result.score) in report
    assert result.summary in report


def test_clean_code_review():
    """测试干净代码的审查。"""
    reviewer = CodeReviewer()
    report_generator = ReviewReportGenerator()

    code = """
def hello() -> None:
    print("Hello, world!")

def add(a: int, b: int) -> int:
    return a + b
"""

    # 1. 审查代码
    result = reviewer.review(code, language="python")

    assert result.score >= 90
    assert len(result.issues) == 0

    # 2. 生成报告
    report = report_generator.generate(result)

    assert "未发现" in report or "✅" in report


def test_review_with_markdown_report():
    """测试生成 Markdown 格式的审查报告。"""
    reviewer = CodeReviewer()
    report_generator = ReviewReportGenerator()

    code = """
def add(a, b):
    return a + b
"""

    result = reviewer.review(code, language="python")
    report = report_generator.generate_markdown(result)

    assert "##" in report
    assert "代码审查" in report


def test_review_score_calculation():
    """测试审查分数计算。"""
    reviewer = CodeReviewer()

    # 完美代码
    perfect_code = """
def hello() -> None:
    print("Hello")
"""
    perfect_result = reviewer.review(perfect_code, language="python")
    assert perfect_result.score == 100

    # 有问题的代码
    bad_code = """
try:
    pass
except:
    pass

def add(a, b):
    return a + b
"""
    bad_result = reviewer.review(bad_code, language="python")
    assert bad_result.score < perfect_result.score
