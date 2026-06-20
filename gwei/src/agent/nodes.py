# src/agent/nodes.py
import json
from src.agent.state import AgentState, SessionStatus, IssueType
from src.services.llm import LLMService


def classify_issue_type(state: AgentState) -> dict:
    """根据 Issue 标题和内容判断类型（降级方案）。"""
    title = state.get("issue_title", "").lower()
    body = state.get("issue_body", "").lower()
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


async def analyze_issue(state: AgentState) -> dict:
    """分析 Issue，调用 LLM 判断类型并生成分析报告。"""
    title = state.get("issue_title", "")
    body = state.get("issue_body", "")

    # 尝试调用 LLM
    try:
        llm = LLMService()

        system_prompt = """你是一个代码助手。分析 GitHub Issue 并判断类型。

返回 JSON 格式（不要包含其他内容）：
{
    "type": "bug|feature|docs|unknown",
    "summary": "简短摘要，50字以内",
    "severity": "low|medium|high",
    "suggested_labels": ["label1", "label2"]
}"""

        user_prompt = f"""Issue 标题：{title}

Issue 内容：
{body}"""

        result = await llm.call(system_prompt, user_prompt)

        # 解析 LLM 返回的 JSON
        analysis = json.loads(result.content)

        # 验证返回的类型
        issue_type_str = analysis.get("type", "unknown").lower()
        try:
            issue_type = IssueType(issue_type_str)
        except ValueError:
            issue_type = IssueType.UNKNOWN

        return {
            "status": SessionStatus.GENERATING,
            "issue_type": issue_type,
            "analysis": analysis.get("summary", body[:200]),
            "severity": analysis.get("severity", "medium"),
            "labels": analysis.get("suggested_labels", []),
            "messages": [f"Issue analyzed by LLM as: {issue_type.value}"],
        }

    except Exception as e:
        # LLM 调用失败，降级到关键词匹配
        type_result = classify_issue_type(state)
        issue_type = type_result["issue_type"]

        analysis = (
            f"## Issue Analysis (Fallback)\n\n"
            f"**Type:** {issue_type.value}\n"
            f"**Title:** {title}\n\n"
            f"**Summary:** {body[:200]}\n\n"
            f"**Note:** LLM analysis failed, using keyword matching. Error: {str(e)}"
        )

        return {
            "status": SessionStatus.GENERATING,
            "issue_type": issue_type,
            "analysis": analysis,
            "severity": "medium",
            "labels": [],
            "messages": [f"Issue analyzed by keywords as: {issue_type.value} (LLM failed)"],
        }


def generate_patches(state: AgentState) -> dict:
    """生成三种 Patch 方案。"""
    title = state.get("issue_title", "")

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
    selected = state.get("selected_patch") or "PROPER"
    title = state.get("issue_title", "")
    repo_name = state.get("repo_name", "")

    return {
        "status": SessionStatus.DONE,
        "pr_url": f"https://github.com/{repo_name}/pull/1",
        "pr_number": 1,
        "messages": [
            f"PR created with {selected} fix for: {title}",
            f"PR: https://github.com/{repo_name}/pull/1",
        ],
    }
