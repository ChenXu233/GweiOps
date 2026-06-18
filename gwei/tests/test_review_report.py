# tests/test_review_report.py
import pytest
from src.services.review_report import ReviewReportGenerator
from src.services.code_reviewer import ReviewResult, ReviewIssue


def test_generate_clean_report():
    generator = ReviewReportGenerator()
    result = ReviewResult(issues=[], score=100, summary="No issues found")

    report = generator.generate(result)

    assert "100" in report
    assert "No issues" in report or "✅" in report


def test_generate_report_with_warnings():
    generator = ReviewReportGenerator()
    result = ReviewResult(
        issues=[
            ReviewIssue(severity="warning", message="Missing type hints", line=5),
            ReviewIssue(severity="warning", message="Bare except", line=10),
        ],
        score=80,
        summary="Found 0 errors, 2 warnings",
    )

    report = generator.generate(result)

    assert "80" in report
    assert "Missing type hints" in report
    assert "Bare except" in report


def test_generate_report_with_errors():
    generator = ReviewReportGenerator()
    result = ReviewResult(
        issues=[
            ReviewIssue(severity="error", message="Syntax error", line=1),
        ],
        score=0,
        summary="Found 1 errors, 0 warnings",
    )

    report = generator.generate(result)

    assert "0" in report or "error" in report.lower()
    assert "Syntax error" in report


def test_generate_report_markdown():
    generator = ReviewReportGenerator()
    result = ReviewResult(
        issues=[
            ReviewIssue(severity="warning", message="Test warning", line=5),
        ],
        score=90,
        summary="Found 0 errors, 1 warnings",
    )

    report = generator.generate_markdown(result)

    assert "##" in report  # Markdown 标题
    assert "Test warning" in report
    assert "90" in report


def test_generate_report_empty():
    generator = ReviewReportGenerator()
    result = ReviewResult(issues=[], score=100, summary="No issues")

    report = generator.generate(result)

    assert len(report) > 0
