# tests/test_code_analyzer.py
import pytest
from src.services.code_analyzer import CodeAnalyzer, AnalysisResult


def test_analyzer_init():
    analyzer = CodeAnalyzer()
    assert analyzer is not None


def test_analyze_python_file():
    analyzer = CodeAnalyzer()
    code = """
def hello():
    print("Hello, world!")

class Foo:
    def bar(self):
        return 42
"""
    result = analyzer.analyze(code, language="python")

    assert "hello" in result.functions
    assert "Foo" in result.classes
    assert "bar" in result.methods


def test_analyze_empty_code():
    analyzer = CodeAnalyzer()
    result = analyzer.analyze("", language="python")

    assert result.functions == []
    assert result.classes == []


def test_analyze_syntax_error():
    analyzer = CodeAnalyzer()
    code = "def broken(:"
    result = analyzer.analyze(code, language="python")

    assert result.has_syntax_error is True
    assert result.error_message is not None


def test_analyze_imports():
    analyzer = CodeAnalyzer()
    code = """
import os
from pathlib import Path
import json
"""
    result = analyzer.analyze(code, language="python")

    assert "os" in result.imports
    assert "pathlib" in result.imports
    assert "json" in result.imports


def test_analysis_result_dataclass():
    result = AnalysisResult(
        functions=["foo", "bar"],
        classes=["MyClass"],
        methods=["method1"],
        imports=["os", "sys"],
        has_syntax_error=False,
        error_message=None,
    )

    assert result.functions == ["foo", "bar"]
    assert result.classes == ["MyClass"]
    assert result.has_syntax_error is False


def test_analyze_complex_code():
    analyzer = CodeAnalyzer()
    code = """
import os
from typing import List

class Calculator:
    def __init__(self):
        self.history = []

    def add(self, a: int, b: int) -> int:
        result = a + b
        self.history.append(result)
        return result

    def subtract(self, a: int, b: int) -> int:
        return a - b

def create_calculator() -> Calculator:
    return Calculator()
"""
    result = analyzer.analyze(code, language="python")

    assert "Calculator" in result.classes
    assert "create_calculator" in result.functions
    assert "add" in result.methods
    assert "subtract" in result.methods
