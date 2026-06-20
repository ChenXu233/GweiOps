# plugins/builtin/adapters/github/git.py
import asyncio
from dataclasses import dataclass


@dataclass
class GitResult:
    success: bool
    output: str
    error: str | None


class GitTool:
    """Git 操作工具。"""

    async def _run_git(self, *args: str, cwd: str | None = None) -> GitResult:
        """执行 git 命令。"""
        try:
            process = await asyncio.create_subprocess_exec(
                "git", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await process.communicate()

            return GitResult(
                success=process.returncode == 0,
                output=stdout.decode().strip(),
                error=stderr.decode().strip() if process.returncode != 0 else None,
            )
        except Exception as e:
            return GitResult(success=False, output="", error=str(e))

    async def clone(self, repo_url: str, target_dir: str) -> GitResult:
        """克隆仓库。"""
        return await self._run_git("clone", repo_url, target_dir)

    async def checkout(self, repo_dir: str, branch: str) -> GitResult:
        """切换分支。"""
        return await self._run_git("checkout", branch, cwd=repo_dir)

    async def create_branch(self, repo_dir: str, branch: str) -> GitResult:
        """创建新分支。"""
        return await self._run_git("checkout", "-b", branch, cwd=repo_dir)

    async def commit(self, repo_dir: str, message: str) -> GitResult:
        """提交更改。"""
        # 先 add 所有更改
        await self._run_git("add", ".", cwd=repo_dir)
        return await self._run_git("commit", "-m", message, cwd=repo_dir)

    async def push(self, repo_dir: str, branch: str) -> GitResult:
        """推送更改。"""
        return await self._run_git("push", "origin", branch, cwd=repo_dir)
