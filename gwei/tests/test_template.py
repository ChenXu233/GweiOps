# tests/test_template.py
import pytest
from src.services.template import TemplateEngine


def test_render_patch_options():
    engine = TemplateEngine()
    patches = [
        {"type": "HOTFIX", "risk": "Low", "description": "Quick fix"},
        {"type": "PROPER", "risk": "Medium", "description": "Root cause fix"},
        {"type": "REFACTOR", "risk": "High", "description": "Code refactoring"},
    ]

    result = engine.render_patch_options(patches)

    assert "方案 A" in result
    assert "HOTFIX" in result
    assert "Quick fix" in result
    assert "方案 B" in result
    assert "PROPER" in result
    assert "方案 C" in result
    assert "REFACTOR" in result


def test_render_patch_options_empty():
    engine = TemplateEngine()
    result = engine.render_patch_options([])
    assert "无可用方案" in result or result == ""


def test_render_analysis_report():
    engine = TemplateEngine()
    analysis = {
        "type": "bug",
        "title": "Parser crash",
        "summary": "The parser crashes on null input",
    }

    result = engine.render_analysis_report(analysis)

    assert "bug" in result
    assert "Parser crash" in result
    assert "The parser crashes on null input" in result


def test_render_duplicate_comment():
    engine = TemplateEngine()
    result = engine.render_duplicate_comment(
        original_issue=42,
        similarity=0.95,
    )

    assert "42" in result
    assert "0.95" in result or "95%" in result


def test_render_incomplete_comment():
    engine = TemplateEngine()
    result = engine.render_incomplete_comment(
        missing_fields=["reproduction", "expected"],
    )

    assert "reproduction" in result
    assert "expected" in result


def test_render_waiting_comment():
    engine = TemplateEngine()
    patches = [
        {"type": "HOTFIX", "risk": "Low", "description": "Quick fix"},
        {"type": "PROPER", "risk": "Medium", "description": "Root cause fix"},
    ]

    result = engine.render_waiting_comment(patches)

    assert "A" in result or "B" in result
    assert "选择" in result or "回复" in result
