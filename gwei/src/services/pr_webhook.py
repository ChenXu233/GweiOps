# src/services/pr_webhook.py
import asyncio

from src.services.voting import VotingService


def analyze_pr_changes(files: list[dict]) -> dict:
    """分析 PR 修改范围，计算风险分数。"""
    risk_score = 0
    core_changes = False

    core_patterns = ["src/parser", "src/lexer", "src/type_checker", "src/codegen"]

    for file in files:
        filename = file.get("filename", "")

        # 检查是否是核心文件
        if any(pattern in filename for pattern in core_patterns):
            core_changes = True
            risk_score += 30

        # 检查删除
        deletions = file.get("deletions", 0)
        if deletions > 10:
            risk_score += 20

        # 检查修改量
        changes = file.get("changes", 0)
        if changes > 100:
            risk_score += 10

    # 计算投票阈值
    if risk_score >= 60:
        min_approvals = 3
    elif risk_score >= 30:
        min_approvals = 2
    else:
        min_approvals = 1

    return {
        "risk_score": risk_score,
        "min_approvals": min_approvals,
        "core_changes": core_changes,
    }


async def process_pr_event(payload: dict) -> dict:
    """处理 PR 事件。"""
    action = payload.get("action")
    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {})

    if action == "opened":
        # 分析 PR 修改
        files = pr.get("files", [])
        analysis = analyze_pr_changes(files)

        # 兼容 AsyncMock（测试中可能将 analyze_pr_changes 替换为异步 Mock）
        if asyncio.iscoroutine(analysis):
            analysis = await analysis

        return {
            "status": "ok",
            "action": action,
            "pr_number": pr.get("number"),
            "risk_score": analysis["risk_score"],
            "min_approvals": analysis["min_approvals"],
        }

    elif action == "synchronize":
        # PR 更新
        return {
            "status": "ok",
            "action": action,
            "pr_number": pr.get("number"),
        }

    return {"status": "ignored", "action": action}


async def process_comment_event(payload: dict) -> dict:
    """处理评论事件。"""
    comment = payload.get("comment", {})
    issue = payload.get("issue", {})

    body = comment.get("body", "").strip()

    # 检查是否是投票
    vote_keywords = {
        "approve": ["同意", "approve", "lgtm", "looks good"],
        "reject": ["反对", "reject", "不同意"],
    }

    vote = None
    for vote_type, keywords in vote_keywords.items():
        if any(kw in body.lower() for kw in keywords):
            vote = vote_type
            break

    if vote:
        # 处理投票
        return {
            "status": "ok",
            "action": "vote",
            "vote": vote,
            "voter_id": comment.get("user", {}).get("id"),
        }

    return {"status": "ok", "action": "comment"}


async def process_vote(repo: str, pr_number: int, voter_id: int, vote: str) -> dict:
    """处理投票请求。"""
    return {"success": False, "message": "Not implemented"}
