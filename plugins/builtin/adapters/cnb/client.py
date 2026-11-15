# plugins/builtin/adapters/cnb/client.py
"""CNB OpenAPI 客户端 —— 回评、开 PR、取仓库快照、问分支。

地址与令牌来自 `CNBConfig`;这里只认 CNB 的接口形状,不往核心漏字段名。
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import CNBConfig


class CNBError(RuntimeError):
    """CNB 明确拒绝了这次调用。带状态码,调用方据此判断"确认没生效"。"""

    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code

    @property
    def not_applied(self) -> bool:
        """4xx 说明对面什么都没做;5xx 与超时说不清。"""
        return 400 <= self.status_code < 500


class CNBClient:
    def __init__(self, config: CNBConfig, timeout_s: float = 60.0) -> None:
        self._config = config
        self._timeout_s = timeout_s

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._config.token}",
            "Accept": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self._config.base_url}{path}"

    async def _request(
        self, method: str, path: str, *, json: dict[str, Any] | None = None
    ) -> httpx.Response:
        if not self._config.token:
            raise CNBError("没配 CNB_TOKEN:回评、开 PR、读仓库都要它", status_code=0)
        async with httpx.AsyncClient(
            follow_redirects=True, timeout=self._timeout_s
        ) as client:
            try:
                response = await client.request(
                    method, self._url(path), headers=self._headers(), json=json
                )
            except httpx.HTTPError as exc:
                raise CNBError(f"CNB 请求失败:{exc}") from exc
        if response.status_code >= 400:
            body = response.text[:300]
            raise CNBError(
                f"CNB {method} {path} → HTTP {response.status_code}:{body}",
                status_code=response.status_code,
            )
        return response

    async def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._request(method, path, **kwargs)
        if not response.content:
            return None
        return response.json()

    # -- 读 --------------------------------------------------------------

    async def repo_info(self, repo: str) -> dict[str, Any]:
        """仓库的默认分支等元信息。CNB 的仓库名是 `group/name`。"""
        return await self._json("GET", f"/{repo}") or {}

    async def default_branch(self, repo: str) -> str:
        info = await self.repo_info(repo)
        return str(info.get("default_branch") or info.get("defaultBranch") or "")

    async def get_pull(self, repo: str, number: int) -> dict[str, Any] | None:
        try:
            return await self._json("GET", f"/{repo}/-/pulls/{number}")
        except CNBError as exc:
            if exc.status_code == 404:
                return None
            raise

    async def create_comment(
        self, repo: str, issue_number: int, body: str, *, is_pull: bool = False
    ) -> dict[str, Any]:
        """在议题或合并请求上发一条评论。

        CNB 上这是两个地址(PR 评论带 `?type=pr`),不是 GitHub 那种"PR 也是 issue"。
        照抄 GitHub 的写法会把评论落到一个同编号的议题上,而人看的是 PR。
        """
        query = "?type=pr" if is_pull else ""
        path = f"/{repo}/-/issues/{issue_number}/comments{query}"
        return await self._json("POST", path, json={"body": body}) or {}

    async def delete_comment(
        self, repo: str, comment_id: int, *, is_pull: bool = False
    ) -> None:
        query = "?type=pr" if is_pull else ""
        await self._request(
            "DELETE", f"/{repo}/-/issues/comments/{comment_id}{query}"
        )

    async def create_pull(
        self,
        repo: str,
        *,
        head: str,
        base: str,
        title: str,
        body: str = "",
    ) -> dict[str, Any]:
        return await self._json(
            "POST",
            f"/{repo}/-/pulls",
            json={"head": head, "base": base, "title": title, "body": body},
        ) or {}

    async def close_pull(self, repo: str, number: int) -> None:
        await self._request("PATCH", f"/{repo}/-/pulls/{number}", json={"state": "closed"})

    async def create_branch(self, repo: str, branch: str, sha: str) -> None:
        await self._request(
            "POST", f"/{repo}/-/git/refs", json={"ref": f"refs/heads/{branch}", "sha": sha}
        )

    async def branch_sha(self, repo: str, branch: str) -> str | None:
        try:
            data = await self._json("GET", f"/{repo}/-/git/refs/heads/{branch}")
        except CNBError as exc:
            if exc.status_code == 404:
                return None
            raise
        if isinstance(data, dict):
            return str(data.get("sha") or data.get("object", {}).get("sha") or "") or None
        return None

    # -- 工作区 ----------------------------------------------------------

    async def archive_url(self, repo: str, branch: str) -> str:
        """整棵树的归档下载地址。CNB 的 web 端给的是 tar.gz。"""
        base = self._config.web_base_url
        return f"{base}/{repo}/-/archive/{branch}.tar.gz"
