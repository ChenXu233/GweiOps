# src/agent/nodes.py
from src.agent.state import AgentState, SessionStatus, IssueType


def classify_issue_type(state: AgentState) -> dict:
    """根据 Issue 标题和内容判断类型。"""
    title = state.issue_title.lower()
    body = state.issue_body.lower()
    combined = f"{title} {body}"

    bug_keywords = ["crash", "bug", "error", "fail", "broken", "null", "segfault", "panic", "崩溃", "报错"]
    feature_keywords = ["add", "feature", "support", "implement", "新增", "支持", "实现"]
    docs_keywords = ["doc", "readme", "document", "文档", "说明"]

    if any(kw in combined for kw in bug_keywords):
        return {"issue_type": IssueType.BUG}
    if any(kw in combined for kw in docs_keywords):
        return {"issue_type": IssueType.DOCS}
    if any(kw in combined for kw in feature_keywords):
        return {"issue_type": IssueType.FEATURE}

    return {"issue_type": IssueType.UNKNOWN}


def analyze_issue(state: AgentState) -> dict:
    """分析 Issue，判断类型并生成分析报告。"""
    issue_type = state.issue_type
    if issue_type is None:
        type_result = classify_issue_type(state)
        issue_type = type_result["issue_type"]

    title = state.issue_title
    body = state.issue_body

    analysis = (
        f"## Issue Analysis\n\n"
        f"**Type:** {issue_type.value}\n"
        f"**Title:** {title}\n\n"
        f"**Summary:** {body[:200]}\n"
    )

    return {
        "status": SessionStatus.GENERATING,
        "issue_type": issue_type,
        "analysis": analysis,
        "messages": [f"Issue analyzed as: {issue_type.value}"],
    }


def generate_patches(state: AgentState) -> dict:
    """生成三种 Patch 方案。"""
    title = state.issue_title

    patches = [
        {
            "type": "HOTFIX",
            "diff": f"# Hotfix for: {title}\n# Minimal change to fix the immediate issue",
            "risk": "Low",
            "description": f"Quick fix for: {title}. Minimal change, fast resolution.",
        },
        {
            "type": "PROPER",
            "diff": f"# Proper fix for: {title}\n# Root cause fix",
            "risk": "Medium",
            "description": f"Root cause fix for: {title}. Recommended approach.",
        },
        {
            "type": "REFACTOR",
            "diff": f"# Refactor for: {title}\n# Code restructuring for long-term maintainability",
            "risk": "High",
            "description": f"Code refactoring for: {title}. Long-term maintainability improvement.",
        },
    ]

    return {
        "status": SessionStatus.WAITING,
        "patches": patches,
        "messages": ["Generated 3 patch options: HOTFIX, PROPER, REFACTOR"],
    }


def wait_for_user_selection(state: AgentState) -> dict:
    """等待用户选择方案。"""
    return {
        "messages": ["Waiting for user to select a patch option (A/B/C)"],
    }


def create_pr(state: AgentState) -> dict:
    """创建 PR。"""
    selected = state.selected_patch or "PROPER"
    title = state.issue_title

    return {
        "status": SessionStatus.DONE,
        "pr_url": f"https://github.com/{state.repo_name}/pull/1",
        "pr_number": 1,
        "messages": [
            f"PR created with {selected} fix for: {title}",
            f"PR: https://github.com/{state.repo_name}/pull/1",
        ],
    }
