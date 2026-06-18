# src/services/voting.py
from dataclasses import dataclass, field


@dataclass
class VoteStatus:
    approvals: int
    rejections: int
    is_approved: bool


@dataclass
class VoteResult:
    success: bool
    message: str


class VotingService:
    """投票系统。管理 PR 的协作者投票。"""

    def __init__(self, min_approvals: int = 2, owner_can_override: bool = True):
        self.min_approvals = min_approvals
        self.owner_can_override = owner_can_override
        self._votes: dict[int, list[dict]] = {}  # pr_id -> votes

    def add_vote(
        self,
        pr_id: int,
        voter_id: int,
        voter_role: str,
        vote: str,
        comment: str | None = None,
    ) -> VoteResult:
        """添加投票。"""
        # 检查是否是协作者
        if voter_role not in ("owner", "collaborator"):
            return VoteResult(
                success=False,
                message=f"User role '{voter_role}' is not eligible to vote",
            )

        # 初始化投票列表
        if pr_id not in self._votes:
            self._votes[pr_id] = []

        # 检查是否已投票
        for existing_vote in self._votes[pr_id]:
            if existing_vote["voter_id"] == voter_id:
                return VoteResult(
                    success=False,
                    message="User has already voted on this PR",
                )

        # 记录投票
        self._votes[pr_id].append({
            "voter_id": voter_id,
            "voter_role": voter_role,
            "vote": vote,
            "comment": comment,
        })

        return VoteResult(success=True, message="Vote recorded")

    def get_status(self, pr_id: int) -> VoteStatus:
        """获取投票状态。"""
        votes = self._votes.get(pr_id, [])

        approvals = 0
        rejections = 0

        for vote in votes:
            if vote["vote"] == "approve":
                approvals += 1
            elif vote["vote"] == "reject":
                rejections += 1

        # Owner 可以单人决定
        if self.owner_can_override:
            for vote in votes:
                if vote["voter_role"] == "owner" and vote["vote"] == "approve":
                    return VoteStatus(
                        approvals=approvals,
                        rejections=rejections,
                        is_approved=True,
                    )

        # 检查是否达到阈值
        is_approved = approvals >= self.min_approvals

        return VoteStatus(
            approvals=approvals,
            rejections=rejections,
            is_approved=is_approved,
        )
