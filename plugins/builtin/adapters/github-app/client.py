# plugins/builtin/adapters/github-app/client.py
"""GitHub App 客户端 - 使用 githubkit 进行 GitHub App 认证和 API 调用。"""

from __future__ import annotations

from typing import Any, Optional

from githubkit import GitHub, AppInstallationAuthStrategy
from githubkit.exception import RequestFailed

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

    def _parse_repo(self, repo: str) -> tuple[str, str]:
        """解析仓库全名为 owner 和 repo_name。

        Args:
            repo: 仓库全名，例如 "owner/repo"

        Returns:
            (owner, repo_name) 元组

        Raises:
            ValueError: 如果仓库名称格式不正确（不包含 "/"）
        """
        parts = repo.split("/", 1)
        if len(parts) != 2:
            raise ValueError(f"仓库名称格式错误：'{repo}'，期望格式为 'owner/repo'")
        return (parts[0], parts[1])

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
        owner, repo_name = self._parse_repo(repo)
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
        owner, repo_name = self._parse_repo(repo)
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
        owner, repo_name = self._parse_repo(repo)
        response = await self.github.rest.issues.async_update_comment(
            owner=owner, repo=repo_name, comment_id=comment_id, body=body
        )
        return response.parsed_data.model_dump()

    async def get_comment(self, repo: str, comment_id: int) -> dict[str, Any] | None:
        """按 ID 取单条评论;不存在时返回 None(撤销后用它验证)。"""
        owner, repo_name = self._parse_repo(repo)
        try:
            response = await self.github.rest.issues.async_get_comment(
                owner=owner, repo=repo_name, comment_id=comment_id
            )
        except RequestFailed as e:
            if e.response.status_code == 404:
                return None
            raise
        return response.parsed_data.model_dump()

    async def delete_comment(self, repo: str, comment_id: int) -> None:
        """删除评论——评论效果的撤销动作。"""
        owner, repo_name = self._parse_repo(repo)
        await self.github.rest.issues.async_delete_comment(
            owner=owner, repo=repo_name, comment_id=comment_id
        )

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
        owner, repo_name = self._parse_repo(repo)
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
        owner, repo_name = self._parse_repo(repo)
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
        owner, repo_name = self._parse_repo(repo)
        response = await self.github.rest.issues.async_list_comments(
            owner=owner, repo=repo_name, issue_number=issue_number
        )
        return [comment.model_dump() for comment in response.parsed_data]

    # -- PR:VCS 操作在平台这一侧做 ----------------------------------
    #
    # 容器里不放 git 凭据。agent 改的是工作区里的文件,平台用 App 安装令牌
    # 把这些改动变成一个提交、一条分支、一个 PR —— 这样"开一个 PR"才是一个
    # 可撤销、可验证的变更单元,而不是容器里一次看不见的 push。

    async def default_branch(self, repo: str) -> str:
        """仓库的默认分支。

        不默认成 main:这个仓库叫 master。调用方推断不出来的东西,API 早就知道。
        """
        owner, repo_name = self._parse_repo(repo)
        response = await self.github.rest.repos.async_get(owner, repo_name)
        data = response.parsed_data.model_dump()
        return str(data.get("default_branch") or "")

    async def installation_token(self) -> str:
        """换一张安装令牌,只用来拉一次代码。

        走 App 的 JWT(AppAuthStrategy)换,和业务调用用的安装认证分开:这张令牌
        有寿命、只在这一次 clone 的命令行里出现,不会进 .git/config,也不会进容器。
        """
        from githubkit import AppAuthStrategy, GitHub

        app = GitHub(
            AppAuthStrategy(app_id=self._config.app_id, private_key=self._config.private_key)
        )
        response = await app.rest.apps.async_create_installation_access_token(
            self._config.installation_id
        )
        return response.parsed_data.token

    async def get_branch_sha(self, repo: str, branch: str) -> str | None:
        """分支头的 sha;分支不存在返回 None。"""
        owner, repo_name = self._parse_repo(repo)
        try:
            response = await self.github.rest.git.async_get_ref(
                owner, repo_name, f"heads/{branch}"
            )
        except RequestFailed as e:
            if e.response.status_code == 404:
                return None
            raise
        # githubkit 把 object 改成了 object_(和 Python 关键字撞名),按字典取更稳
        data = response.parsed_data.model_dump()
        return (data.get("object") or data.get("object_") or {}).get("sha")

    async def create_branch(self, repo: str, branch: str, from_sha: str) -> None:
        owner, repo_name = self._parse_repo(repo)
        await self.github.rest.git.async_create_ref(
            owner, repo_name, data={"ref": f"refs/heads/{branch}", "sha": from_sha}
        )

    async def delete_branch(self, repo: str, branch: str) -> None:
        owner, repo_name = self._parse_repo(repo)
        await self.github.rest.git.async_delete_ref(owner, repo_name, f"heads/{branch}")

    async def commit_files(
        self, repo: str, branch: str, files: list[dict[str, Any]], message: str
    ) -> str:
        """在分支上追加一个提交,返回提交 sha。

        files 每项是 {path, content};删文件写 {path, delete: true}。
        一次提交改多个文件,所以走 Git Data API:blob → tree → commit → 移动分支头。
        """
        owner, repo_name = self._parse_repo(repo)
        head = await self.get_branch_sha(repo, branch)
        if head is None:
            raise ValueError(f"分支不存在:{branch}")
        parent = await self.github.rest.git.async_get_commit(owner, repo_name, head)

        entries: list[dict[str, Any]] = []
        for item in files:
            path = str(item.get("path") or "")
            if not path:
                raise ValueError("files 里有一项没有 path")
            if item.get("delete"):
                # sha 为 None 表示从这个 tree 里删掉这条路径
                entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
                continue
            blob = await self.github.rest.git.async_create_blob(
                owner, repo_name, data={"content": item.get("content", ""), "encoding": "utf-8"}
            )
            entries.append(
                {"path": path, "mode": "100644", "type": "blob", "sha": blob.parsed_data.sha}
            )

        tree = await self.github.rest.git.async_create_tree(
            owner, repo_name, data={"tree": entries, "base_tree": parent.parsed_data.tree.sha}
        )
        commit = await self.github.rest.git.async_create_commit(
            owner,
            repo_name,
            data={"message": message, "tree": tree.parsed_data.sha, "parents": [head]},
        )
        await self.github.rest.git.async_update_ref(
            owner, repo_name, f"heads/{branch}", data={"sha": commit.parsed_data.sha}
        )
        return commit.parsed_data.sha

    async def open_pull(
        self, repo: str, head: str, base: str, title: str, body: str = ""
    ) -> dict[str, Any]:
        owner, repo_name = self._parse_repo(repo)
        response = await self.github.rest.pulls.async_create(
            owner, repo_name,
            data={"title": title, "head": head, "base": base, "body": body},
        )
        return response.parsed_data.model_dump()

    async def get_pull_by_head(self, repo: str, head: str) -> dict[str, Any] | None:
        """这条分支上的 PR(含已关闭的),没有返回 None。

        同一条分支只该有一个 PR:"接着这个 PR 改"和"再开一个 PR"是两件事,
        分不清就会出现两条并行的分支,而人只能看见其中一条。
        """
        owner, repo_name = self._parse_repo(repo)
        response = await self.github.rest.pulls.async_list(
            owner, repo_name, head=f"{owner}:{head}", state="all"
        )
        items = [item.model_dump() for item in response.parsed_data]
        return items[0] if items else None

    async def get_pull(self, repo: str, number: int) -> dict[str, Any] | None:
        """按编号取 PR;不存在返回 None(撤销后用它验证)。"""
        owner, repo_name = self._parse_repo(repo)
        try:
            response = await self.github.rest.pulls.async_get(owner, repo_name, number)
        except RequestFailed as e:
            if e.response.status_code == 404:
                return None
            raise
        return response.parsed_data.model_dump()

    async def close_pull(self, repo: str, number: int) -> None:
        owner, repo_name = self._parse_repo(repo)
        await self.github.rest.pulls.async_update(
            owner, repo_name, number, data={"state": "closed"}
        )
