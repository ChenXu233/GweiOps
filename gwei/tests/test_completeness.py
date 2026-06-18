# tests/test_completeness.py
import pytest
from src.services.completeness import CompletenessChecker, CompletenessReport


def test_checker_default_required_fields():
    checker = CompletenessChecker()
    assert "reproduction" in checker.required_fields
    assert "expected" in checker.required_fields
    assert "actual" in checker.required_fields


def test_checker_custom_required_fields():
    checker = CompletenessChecker(required_fields=["steps", "expected", "actual"])
    assert checker.required_fields == ["steps", "expected", "actual"]


def test_check_complete_issue():
    checker = CompletenessChecker()
    body = """
## 复现步骤
1. 打开应用
2. 点击按钮
3. 观察崩溃

## 期望行为
应用应该正常运行

## 实际行为
应用崩溃并显示错误
"""
    report = checker.check(body)
    assert report.is_complete is True
    assert report.missing_fields == []


def test_check_incomplete_issue():
    checker = CompletenessChecker()
    body = """
## 复现步骤
1. 打开应用
2. 点击按钮
"""
    report = checker.check(body)
    assert report.is_complete is False
    assert "expected" in report.missing_fields or "actual" in report.missing_fields


def test_check_empty_body():
    checker = CompletenessChecker()
    report = checker.check("")
    assert report.is_complete is False
    assert len(report.missing_fields) > 0


def test_check_all_missing():
    checker = CompletenessChecker()
    report = checker.check("This is a vague issue")
    assert report.is_complete is False
    assert len(report.missing_fields) == 3


def test_completeness_report_dataclass():
    report = CompletenessReport(is_complete=True, missing_fields=[], score=1.0)
    assert report.is_complete is True
    assert report.score == 1.0


def test_check_partial_match():
    checker = CompletenessChecker()
    body = """
## Expected Behavior
Should work correctly

## Actual Behavior
Crashes
"""
    report = checker.check(body)
    # 缺少 reproduction
    assert report.is_complete is False
    assert "reproduction" in report.missing_fields
