# tests/test_phase3_integration.py
import pytest
from src.services.git_tool import GitTool
from src.services.code_analyzer import CodeAnalyzer
from src.services.patch_generator import PatchGenerator


def test_full_bug_fix_flow():
    """测试完整的 Bug 修复流程：分析代码 -> 生成 Patch。"""
    analyzer = CodeAnalyzer()
    generator = PatchGenerator()

    # 1. 分析代码
    code = """
def process_input(data):
    return data.process()

class Parser:
    def parse(self, text):
        return text.split()
"""
    analysis = analyzer.analyze(code, language="python")

    assert "process_input" in analysis.functions
    assert "Parser" in analysis.classes
    assert "parse" in analysis.methods

    # 2. 生成修复方案
    patches = generator.generate_all(
        issue_title="Parser crash on null",
        issue_body="Crash when input is null",
        file_path="src/parser.py",
    )

    assert len(patches) == 3

    # 验证每种方案
    hotfix = next(p for p in patches if p.type == "HOTFIX")
    proper = next(p for p in patches if p.type == "PROPER")
    refactor = next(p for p in patches if p.type == "REFACTOR")

    assert hotfix.risk == "Low"
    assert proper.risk == "Medium"
    assert refactor.risk == "High"

    # 3. 验证 diff 内容
    for patch in patches:
        assert len(patch.diff) > 0
        assert "parser.py" in patch.diff or "file.py" in patch.diff


def test_code_analysis_with_syntax_error():
    """测试语法错误的代码分析。"""
    analyzer = CodeAnalyzer()

    code = "def broken(:"
    result = analyzer.analyze(code, language="python")

    assert result.has_syntax_error is True
    assert result.error_message is not None


def test_patch_generation_with_context():
    """测试带上下文的 Patch 生成。"""
    generator = PatchGenerator()

    patches = generator.generate_all(
        issue_title="Add JSON support",
        issue_body="Need JSON output",
        file_path="src/output.py",
        context={"language": "python", "framework": "fastapi"},
    )

    assert len(patches) == 3

    # 每个方案都应该有不同的风险级别
    risks = [p.risk for p in patches]
    assert "Low" in risks
    assert "Medium" in risks
    assert "High" in risks


def test_git_tool_result_structure():
    """测试 Git 工具结果结构。"""
    from src.services.git_tool import GitResult

    result = GitResult(success=True, output="commit abc123", error=None)

    assert result.success is True
    assert result.output == "commit abc123"
    assert result.error is None

    # 失败情况
    result = GitResult(success=False, output="", error="fatal: error")

    assert result.success is False
    assert result.error == "fatal: error"
