# src/services/reproducer.py
import asyncio
from dataclasses import dataclass
from src.services.git_tool import GitTool


@dataclass
class ReproductionResult:
    success: bool
    error_output: str | None = None
    stack_trace: str | None = None
    error: str | None = None


class BugReproducer:
    """Bug 复现服务。在隔离环境中复现 Bug。"""

    def __init__(self, timeout: int = 300, work_dir: str = "/tmp/gwei"):
        self.timeout = timeout
        self.work_dir = work_dir
        self.git_tool = GitTool()

    async def reproduce(
        self,
        repo_url: str,
        issue_number: int,
        steps: list[str],
        branch: str | None = None,
    ) -> ReproductionResult:
        """复现 Bug。"""
        try:
            # 1. 克隆仓库
            repo_dir = f"{self.work_dir}/issue-{issue_number}"
            clone_result = await self._clone_repo(repo_url, repo_dir, branch)

            if not clone_result:
                return ReproductionResult(
                    success=False,
                    error="Failed to clone repository",
                )

            # 2. 执行复现步骤
            result = await asyncio.wait_for(
                self._run_reproduction(repo_dir, steps),
                timeout=self.timeout,
            )

            return result

        except TimeoutError:
            return ReproductionResult(
                success=False,
                error="Reproduction timed out due to timeout",
            )
        except Exception as e:
            return ReproductionResult(
                success=False,
                error=str(e),
            )

    async def _clone_repo(self, repo_url: str, target_dir: str, branch: str | None = None) -> bool:
        """克隆仓库。"""
        result = await self.git_tool.clone(repo_url, target_dir)

        if not result.success:
            return False

        if branch:
            checkout_result = await self.git_tool.checkout(target_dir, branch)
            return checkout_result.success

        return True

    async def _run_reproduction(self, repo_dir: str, steps: list[str]) -> ReproductionResult:
        """执行复现步骤。"""
        error_output = ""
        stack_trace = ""

        for step in steps:
            # 执行命令
            process = await asyncio.create_subprocess_shell(
                step,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=repo_dir,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_output = stderr.decode().strip()
                stack_trace = self._extract_stack_trace(error_output)

                return ReproductionResult(
                    success=True,
                    error_output=error_output,
                    stack_trace=stack_trace,
                )

        return ReproductionResult(
            success=False,
            error="No error reproduced",
        )

    def _extract_stack_trace(self, error_output: str) -> str | None:
        """从错误输出中提取堆栈跟踪。"""
        lines = error_output.split("\n")
        trace_lines = []

        for line in lines:
            if "at " in line or "Traceback" in line or "File " in line:
                trace_lines.append(line)

        return "\n".join(trace_lines) if trace_lines else None
