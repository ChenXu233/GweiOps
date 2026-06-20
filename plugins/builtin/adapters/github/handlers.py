# plugins/builtin/adapters/github/handlers.py


async def process_issue_event(event: str, payload: dict) -> dict:
    action = payload.get("action")
    issue = payload.get("issue", {})
    repo = payload.get("repository", {})

    if action == "opened":
        # NOTE: 原有的 agent graph 调用已移除，由 plugin.py 的 handle_event 统一调度
        # 如需重新集成 agent，请通过插件系统注入依赖
        return {
            "status": "ok",
            "action": action,
            "issue_number": issue.get("number", 0),
            "repo_name": repo.get("full_name", ""),
        }

    return {"status": "ignored", "action": action}
