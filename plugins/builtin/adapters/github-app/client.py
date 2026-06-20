# plugins/builtin/adapters/github-app/client.py
"""GitHub App 客户端 - 使用 githubkit 进行 GitHub App 认证和 API 调用。"""

from __future__ import annotations

from typing import Any, Optional

from githubkit import GitHub, AppInstallationAuthStrategy

from .config import GitHubAppConfig


class GitHubAppClient:
    """GitHub App 客户端，使用 githubkit 进行认证和 API 调用。"""

    def __init__(self, config: Optional[GitHubAppConfig] = None):
        """初始化 GitHub App 客户端。

        Args:
            config: GitHub App 配置。如果未提供，将使用默认配置。
        """
        self._config = config or GitHubAppConfig()
        self._github: Optional[GitHub] = None

    @property
    def github(self) -> GitHub:
        """获取 GitHub 实例（懒加载）。"""
        if self._github is None:
            self._github = GitHub(
                AppInstallationAuthStrategy(
                    app_id=self._config.app_id,
                    private_key=self._config.private_key,
                    installation_id=self._config.installation_id,
                )
            )
        return self._github

    async def get_issue(self, repo: str, issue_number: int) -> dict[str, Any]:
        """获取 issue 详情。

        Args:
            repo: 仓库全名，例如 "owner/repo"
            issue_number: Issue 编号

        Returns:
            Issue 详情字典
        """
        owner, repo_name = repo.split("/", 1)
        response = await self.github.rest.issues.async_get(
            owner=owner, repo=repo_name, issue_number=issue_number
        )
        return response.parsed_data.model_dump()

    async def create_comment(self, repo: str, issue_number: int, body: str) -> dict[str, Any]:
        """在 issue 上创建评论。

        Args:
            repo: 仓库全名，例如 "owner/repo"
            issue_number: Issue 编号
            body: 评论内容（Markdown 格式）

        Returns:
            创建的评论详情
        """
        owner, repo_name = repo.split("/", 1)
        response = await self.github.rest.issues.async_create_comment(
            owner=owner, repo=repo_name, issue_number=issue_number, body=body
        )
        return response.parsed_data.model_dump()

    async def update_comment(
        self, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]:
        """更新评论。

        Args:
            repo: 仓库全名，例如 "owner/repo"
            comment_id: 评论 ID
            body: 新的评论内容（Markdown 格式）

        Returns:
            更新后的评论详情
        """
        owner, repo_name = repo.split("/", 1)
        response = await self.github.rest.issues.async_update_comment(
            owner=owner, repo=repo_name, comment_id=comment_id, body=body
        )
        return response.parsed_data.model_dump()

    async def add_labels(
        self, repo: str, issue_number: int, labels: list[str]
    ) -> dict[str, Any]:
        """为 issue 添加标签。

        Args:
            repo: 仓库全名，例如 "owner/repo"
            issue_number: Issue 编号
            labels: 要添加的标签列表

        Returns:
            包含更新后标签的响应
        """
        owner, repo_name = repo.split("/", 1)
        response = await self.github.rest.issues.async_add_labels(
            owner=owner, repo=repo_name, issue_number=issue_number, labels=labels
        )
        return {"labels": [label.model_dump() for label in response.parsed_data]}

    async def remove_labels(
        self, repo: str, issue_number: int, labels: list[str]
    ) -> None:
        """从 issue 移除标签。

        Args:
            repo: 仓库全名，例如 "owner/repo"
            issue_number: Issue 编号
            labels: 要移除的标签名称列表
        """
        owner, repo_name = repo.split("/", 1)
        for label in labels:
            await self.github.rest.issues.async_remove_label(
                owner=owner, repo=repo_name, issue_number=issue_number, name=label
            )

    async def get_issue_comments(
        self, repo: str, issue_number: int
    ) -> list[dict[str, Any]]:
        """获取 issue 的所有评论。

        Args:
            repo: 仓库全名，例如 "owner/repo"
            issue_number: Issue 编号

        Returns:
            评论列表
        """
        owner, repo_name = repo.split("/", 1)
        response = await self.github.rest.issues.async_list_comments(
            owner=owner, repo=repo_name, issue_number=issue_number
        )
        return [comment.model_dump() for comment in response.parsed_data]
