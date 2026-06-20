# src/services/pr_creator.py
from dataclasses import dataclass
from src.services.github import GitHubClient


@dataclass
class PRResult:
    success: bool
    pr_number: int | None
    pr_url: str | None
    error: str | None


class PRCreator:
    """创建 Pull Request。"""

    def __init__(self, github: GitHubClient | None = None):
        self.github = github or GitHubClient()

    async def create(
        self,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
        labels: list[str] | None = None,
    ) -> PRResult:
        """创建 PR。"""
        try:
            # 创建 PR
            pr_data = await self.github.create_pr(
                repo=repo,
                title=title,
                head=head,
                base=base,
                body=body,
            )

            # 添加标签
            if labels:
                await self.github.add_labels(
                    repo=repo,
                    issue_number=pr_data["number"],
                    labels=labels,
                )

            return PRResult(
                success=True,
                pr_number=pr_data["number"],
                pr_url=pr_data["url"],
                error=None,
            )
        except Exception as e:
            return PRResult(
                success=False,
                pr_number=None,
                pr_url=None,
                error=str(e),
            )
