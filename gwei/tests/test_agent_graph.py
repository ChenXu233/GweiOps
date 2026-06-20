# tests/test_agent_graph.py
import pytest
from src.agent.state import AgentState, SessionStatus, IssueType
from src.agent.nodes import analyze_issue, classify_issue_type


def test_classify_issue_type_bug():
    state: AgentState = {
        "issue_title": "Fix crash on null pointer",
        "issue_body": "When input is null, the parser crashes with a segfault",
    }
    result = classify_issue_type(state)
    assert result["issue_type"] == IssueType.BUG


def test_classify_issue_type_feature():
    state: AgentState = {
        "issue_title": "Add support for JSON output",
        "issue_body": "It would be great to have JSON output format",
    }
    result = classify_issue_type(state)
    assert result["issue_type"] in (IssueType.FEATURE, IssueType.UNKNOWN)


def test_classify_issue_type_docs():
    state: AgentState = {
        "issue_title": "Update README with examples",
        "issue_body": "The README is missing usage examples",
    }
    result = classify_issue_type(state)
    assert result["issue_type"] in (IssueType.DOCS, IssueType.UNKNOWN)


@pytest.mark.asyncio
async def test_analyze_issue_sets_status():
    state: AgentState = {
        "issue_title": "Bug: crash",
        "issue_body": "App crashes",
        "repo_url": "https://github.com/test/repo",
        "repo_name": "test/repo",
        "issue_number": 1,
    }
    result = await analyze_issue(state)
    assert result["status"] == SessionStatus.GENERATING
    assert len(result["analysis"]) > 0


@pytest.mark.asyncio
async def test_analyze_issue_with_llm_mock():
    """测试 LLM 分析 Issue（模拟模式）。"""
    state: AgentState = {
        "issue_title": "Parser crashes on empty input",
        "issue_body": "When I pass empty string, the parser throws NullPointerError",
    }
    result = await analyze_issue(state)

    # 模拟模式应该返回有效的分析结果
    assert result["status"] == SessionStatus.GENERATING
    assert result["issue_type"] in (IssueType.BUG, IssueType.UNKNOWN)
    assert "analysis" in result
    assert "severity" in result
    assert "labels" in result


def test_route_after_analysis_bug_needs_reproduction():
    from src.agent.graph import route_after_analysis
    state: AgentState = {
        "issue_title": "Crash",
        "issue_body": "Crash on empty input",
        "repo_url": "https://github.com/test/repo",
        "status": SessionStatus.ANALYZING,
        "issue_type": IssueType.BUG,
    }
    assert route_after_analysis(state) == "reproducing"


def test_route_after_analysis_docs_skips_to_generating():
    from src.agent.graph import route_after_analysis
    state: AgentState = {
        "issue_title": "Update docs",
        "issue_body": "Update README",
        "repo_url": "https://github.com/test/repo",
        "status": SessionStatus.ANALYZING,
        "issue_type": IssueType.DOCS,
    }
    assert route_after_analysis(state) == "generating"
