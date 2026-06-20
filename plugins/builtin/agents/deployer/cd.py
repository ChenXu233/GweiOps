# src/services/pr_iteration.py
from dataclasses import dataclass
from src.services.llm import LLMService


@dataclass
class IterationResult:
    success: bool
    action: str  # update_pr, reply, none
    message: str
    diff: str | None = None


class PRIterationService:
    """PR 多轮迭代服务。处理 Review 评论并生成修改。"""

    def __init__(self, llm: LLMService | None = None):
        self.llm = llm or LLMService()

    async def process_review_comment(
        self,
        pr_number: int,
        comment_body: str,
        commenter: str,
    ) -> IterationResult:
        """处理 Review 评论。"""
        # 1. 分析评论类型
        analysis = await self._analyze_comment(comment_body)

        comment_type = analysis.get("type", "unknown")

        if comment_type == "approve":
            return IterationResult(
                success=True,
                action="none",
                message="PR approved",
            )

        elif comment_type == "question":
            # 生成回答
            response = await self._generate_response(analysis.get("question", ""))
            return IterationResult(
                success=True,
                action="reply",
                message=response,
            )

        elif comment_type == "request_changes":
            # 生成修复
            fix = await self._generate_fix(analysis.get("issues", []))
            return IterationResult(
                success=True,
                action="update_pr",
                message=fix.get("description", "Applied fixes"),
                diff=fix.get("diff"),
            )

        return IterationResult(
            success=True,
            action="none",
            message="Comment processed",
        )

    async def _analyze_comment(self, comment_body: str) -> dict:
        """分析评论类型和内容。"""
        comment_lower = comment_body.lower()

        # 检查是否是批准
        approve_keywords = ["lgtm", "approve", "looks good", "同意", "批准"]
        if any(kw in comment_lower for kw in approve_keywords):
            return {"type": "approve"}

        # 检查是否是问题
        question_keywords = ["why", "how", "what", "为什么", "怎么", "什么"]
        if any(kw in comment_lower for kw in question_keywords):
            return {"type": "question", "question": comment_body}

        # 默认为修改请求
        return {
            "type": "request_changes",
            "issues": [comment_body],
        }

    async def _generate_response(self, question: str) -> str:
        """生成问题回答。"""
        system_prompt = """你是一个代码审查助手。请根据问题生成简洁的回答。
        回答应该专业、清晰、有帮助。"""

        result = await self.llm.call(
            system_prompt=system_prompt,
            user_prompt=f"问题：{question}",
        )

        return result.content

    async def _generate_fix(self, issues: list[str]) -> dict:
        """生成修复代码。"""
        system_prompt = """你是一个代码修复助手。请根据代码审查意见生成修复代码。
        输出格式：
        - diff: 代码差异
        - description: 修复描述"""

        issues_text = "\n".join(f"- {issue}" for issue in issues)

        result = await self.llm.call(
            system_prompt=system_prompt,
            user_prompt=f"代码审查意见：\n{issues_text}",
        )

        # 简化版：返回模拟 diff
        return {
            "diff": f"# Fix for: {issues[0] if issues else 'unknown issue'}\n# Applied fix based on review comments",
            "description": f"Fixed: {', '.join(issues)}",
        }
