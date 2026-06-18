# tests/test_agent_state.py
from src.agent.state import AgentState, IssueType, SessionStatus


def test_agent_state_defaults():
    state = AgentState(
        issue_title="Test bug",
        issue_body="Something is broken",
        repo_url="https://github.com/owner/repo",
    )
    assert state.issue_title == "Test bug"
    assert state.issue_body == "Something is broken"
    assert state.status == SessionStatus.INIT
    assert state.issue_type is None
    assert state.patches == []
    assert state.error_count == 0


def test_agent_state_transition():
    state = AgentState(
        issue_title="Bug",
        issue_body="Crash on empty input",
        repo_url="https://github.com/owner/repo",
    )
    state.status = SessionStatus.ANALYZING
    assert state.status == SessionStatus.ANALYZING

    state.issue_type = IssueType.BUG
    assert state.issue_type == IssueType.BUG


def test_agent_state_error_tracking():
    state = AgentState(
        issue_title="Bug",
        issue_body="Crash",
        repo_url="https://github.com/owner/repo",
    )
    assert state.error_count == 0
    state.error_count += 1
    assert state.error_count == 1
    assert not state.should_fail  # 阈值是 3

    state.error_count = 3
    assert state.should_fail


def test_session_status_enum():
    assert SessionStatus.INIT.value == "INIT"
    assert SessionStatus.ANALYZING.value == "ANALYZING"
    assert SessionStatus.REPRODUCING.value == "REPRODUCING"
    assert SessionStatus.GENERATING.value == "GENERATING"
    assert SessionStatus.WAITING.value == "WAITING"
    assert SessionStatus.CREATING_PR.value == "CREATING_PR"
    assert SessionStatus.DONE.value == "DONE"
    assert SessionStatus.FAILED.value == "FAILED"


def test_issue_type_enum():
    assert IssueType.BUG.value == "bug"
    assert IssueType.FEATURE.value == "feature"
    assert IssueType.DOCS.value == "docs"
    assert IssueType.DUPLICATE.value == "duplicate"
    assert IssueType.QUESTION.value == "question"
    assert IssueType.UNKNOWN.value == "unknown"
