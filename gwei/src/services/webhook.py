# src/services/webhook.py
from src.agent.graph import gwei_graph
from src.agent.state import AgentState
from src.services.github import GitHubClient


async def process_issue_event(event: str, payload: dict) -> dict:
    action = payload.get("action")
    issue = payload.get("issue", {})
    repo = payload.get("repository", {})

    if action == "opened":
        initial_state: AgentState = {
            "issue_title": issue.get("title", ""),
            "issue_body": issue.get("body", ""),
            "repo_url": repo.get("clone_url", ""),
            "repo_name": repo.get("full_name", ""),
            "issue_number": issue.get("number", 0),
            "error_count": 0,
            "messages": [],
            "patches": [],
        }

        result = await gwei_graph.ainvoke(initial_state)

        patches = result.get("patches", [])
        if patches:
            client = GitHubClient()
            patch_descriptions = []
            for i, p in enumerate(patches):
                letter = chr(ord("A") + i)
                patch_descriptions.append(
                    f"### 方案 {letter}：{p['type']}\n"
                    f"- **风险**：{p['risk']}\n"
                    f"- **说明**：{p['description']}\n"
                )

            comment_body = (
                "## 🛠️ 修复方案\n\n"
                + "\n".join(patch_descriptions)
                + "\n\n请回复选择方案（A/B/C），或提出修改建议。"
            )

            await client.create_comment(
                repo.get("full_name", ""),
                issue.get("number", 0),
                comment_body,
            )

        return {"status": "ok", "session_status": result.get("status")}

    return {"status": "ignored", "action": action}
