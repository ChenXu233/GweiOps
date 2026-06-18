# tests/test_integration.py
import pytest
from src.services.labeler import LabelGenerator
from src.services.duplicate_detector import DuplicateDetector
from src.services.completeness import CompletenessChecker
from src.services.template import TemplateEngine


def test_full_issue_analysis_flow():
    """测试完整的 Issue 分析流程：标签生成 + 完整性检查 + 重复检测。"""
    labeler = LabelGenerator()
    completeness = CompletenessChecker()
    duplicate_detector = DuplicateDetector(threshold=0.8)
    template = TemplateEngine()

    # 模拟一个 Issue
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

    # 1. 生成标签
    labels = labeler.generate(title=issue_title, body=issue_body)
    assert "parser" in labels
    assert "bug" in labels

    # 2. 检查完整性
    report = completeness.check(issue_body)
    assert report.is_complete is True
    assert report.score == 1.0

    # 3. 检查重复（无现有 Issue）
    dup_result = duplicate_detector.detect(
        title=issue_title,
        body=issue_body,
        existing_issues=[],
    )
    assert dup_result.is_duplicate is False

    # 4. 渲染分析报告
    analysis = {
        "type": "bug",
        "title": issue_title,
        "summary": "Parser crashes on null input",
    }
    report_text = template.render_analysis_report(analysis)
    assert "bug" in report_text
    assert issue_title in report_text


def test_duplicate_detection_flow():
    """测试重复检测流程。"""
    detector = DuplicateDetector(threshold=0.7)

    existing_issues = [
        {"id": 1, "title": "Parser crash on null", "body": "Parser crashes when input is null"},
        {"id": 2, "title": "Lexer bug", "body": "Lexer fails on empty input"},
    ]

    # 测试重复 Issue
    result = detector.detect(
        title="Parser crash on null input",
        body="The parser crashes when input is null",
        existing_issues=existing_issues,
    )

    # 应该检测到与 Issue #1 相似
    assert result.score > 0.5  # 至少有一定相似度


def test_incomplete_issue_flow():
    """测试不完整 Issue 的处理流程。"""
    completeness = CompletenessChecker()
    template = TemplateEngine()

    # 不完整的 Issue
    issue_body = "The parser crashes"

    # 1. 检查完整性
    report = completeness.check(issue_body)
    assert report.is_complete is False
    assert len(report.missing_fields) > 0

    # 2. 渲染不完整评论
    comment = template.render_incomplete_comment(missing_fields=report.missing_fields)
    assert "信息不完整" in comment


def test_patch_selection_flow():
    """测试修复方案选择流程。"""
    template = TemplateEngine()

    patches = [
        {"type": "HOTFIX", "risk": "Low", "description": "Quick fix"},
        {"type": "PROPER", "risk": "Medium", "description": "Root cause fix"},
        {"type": "REFACTOR", "risk": "High", "description": "Code refactoring"},
    ]

    # 1. 渲染方案选项
    options_text = template.render_patch_options(patches)
    assert "方案 A" in options_text
    assert "HOTFIX" in options_text

    # 2. 渲染等待评论
    waiting_text = template.render_waiting_comment(patches)
    assert "选择" in waiting_text or "回复" in waiting_text
