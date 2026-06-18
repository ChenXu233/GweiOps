# tests/test_agent_graph.py
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


def test_analyze_issue_sets_status():
    state: AgentState = {
        "issue_title": "Bug: crash",
        "issue_body": "App crashes",
        "repo_url": "https://github.com/test/repo",
        "repo_name": "test/repo",
        "issue_number": 1,
    }
    result = analyze_issue(state)
    assert result["status"] == SessionStatus.GENERATING
    assert len(result["analysis"]) > 0


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
