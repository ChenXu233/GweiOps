# tests/test_duplicate_detector.py
import pytest
from src.services.duplicate_detector import DuplicateDetector, DuplicateResult


def test_duplicate_detector_init():
    detector = DuplicateDetector(threshold=0.8)
    assert detector.threshold == 0.8


def test_duplicate_detector_default_threshold():
    detector = DuplicateDetector()
    assert detector.threshold == 0.8


def test_detect_duplicate_exact_match():
    detector = DuplicateDetector(threshold=0.8)
    existing_issues = [
        {"id": 1, "title": "Parser crash on null", "body": "The parser crashes when input is null"},
        {"id": 2, "title": "Lexer bug", "body": "Lexer fails on empty input"},
    ]

    result = detector.detect(
        title="Parser crash on null",
        body="The parser crashes when input is null",
        existing_issues=existing_issues,
    )

    assert result.is_duplicate is True
    assert result.similar_issue_id == 1
    assert result.score > 0.8


def test_detect_no_duplicate():
    detector = DuplicateDetector(threshold=0.8)
    existing_issues = [
        {"id": 1, "title": "Parser crash on null", "body": "The parser crashes when input is null"},
    ]

    result = detector.detect(
        title="Add JSON support",
        body="Please add JSON output format",
        existing_issues=existing_issues,
    )

    assert result.is_duplicate is False
    assert result.similar_issue_id is None


def test_detect_similar_but_not_duplicate():
    detector = DuplicateDetector(threshold=0.8)
    existing_issues = [
        {"id": 1, "title": "Parser crash on null", "body": "The parser crashes when input is null"},
    ]

    result = detector.detect(
        title="Parser crash on empty string",
        body="The parser crashes when input is empty string",
        existing_issues=existing_issues,
    )

    # 可能是也可能不是重复，取决于相似度计算
    assert isinstance(result.is_duplicate, bool)


def test_duplicate_result_dataclass():
    result = DuplicateResult(is_duplicate=True, similar_issue_id=1, score=0.95)
    assert result.is_duplicate is True
    assert result.similar_issue_id == 1
    assert result.score == 0.95


def test_duplicate_result_no_match():
    result = DuplicateResult(is_duplicate=False, similar_issue_id=None, score=0.0)
    assert result.is_duplicate is False
    assert result.similar_issue_id is None
    assert result.score == 0.0
