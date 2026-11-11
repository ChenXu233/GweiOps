# engine/harness/adapter.py
"""把一次事故交给外部的 harness。

平台不认识 dsh、codex、claude-code 里的任何一个:它只认一件事——在指定工作区
里跑一条命令,再从约定位置读回一份报告。

**边界由那条命令决定,不由平台决定。** 想让它不和宿主机跑在一起,命令就写
`docker run --rm -v {workspace}:/w ...`;平台不会替你在宿主机上直接起进程。
留空就是不用外部 harness,回落到进程内的 operator 或声明式路径。

这样换来的是:换 harness 不动平台,换边界也不动平台。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPORT_NAME = "report.json"


@dataclass(frozen=True)
class HarnessResult:
    report: dict[str, Any]
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    workspace: str = ""


def build_task(
    *,
    incident_id: str,
    signal: dict[str, Any],
    exit_url: str,
    workspace: str,
    report_path: str,
) -> str:
    """交给 harness 的任务文本。它自己决定怎么查、怎么改,这里只说清楚边界。"""
    detail = str(signal.get("detail") or "").strip()
    lines = [
        "你在处理一次线上事故。",
        "",
        f"事故编号:{incident_id}",
        f"信号:{signal.get('title') or signal.get('subject') or '(未命名)'}",
    ]
    if detail:
        lines.append(f"详情:{detail}")
    lines += [
        "",
        "改变外部世界只能通过出口(每次调用都经过平台判定,可能被拒绝或撤销,",
        "被拒绝时 reason 会写明原因;不要对同一个动作反复试):",
        f"  GET  {exit_url}",
        f"  POST {exit_url}/<能力名>",
        "  GET 时会告诉你这个部署里能做什么、每个动作要哪些参数。",
        "",
        f"工作区在 {workspace}。随便用:读代码、跑测试、改文件都行。",
        "那里没有生产凭据;凭据只在平台那一侧,你拿不到,也不需要。",
        "",
        "拿不准就什么都不做——那是合格的处理。",
        "",
        "收工时把报告写到下面这个路径,UTF-8 的 JSON:",
        f"  {report_path}",
        '  {"summary": "...", "steps": [], "counts": {}, "exhausted": false}',
    ]
    return "\n".join(lines)


def _read_report(workspace: Path) -> dict[str, Any] | None:
    path = workspace / REPORT_NAME
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return value if isinstance(value, dict) else None


def _fallback_report(result: HarnessResult) -> dict[str, Any]:
    """没交报告也要有个交代:退出码、最后几行输出,原样带回来。

    stderr 也要带上——dsh 这类启动器把失败原因(message、缺哪个变量)写在 stderr,
    只看 stdout 等于把「为什么没跑起来」丢掉。
    """
    tail = (result.stdout or "").strip().splitlines()[-8:]
    err_tail = (result.stderr or "").strip().splitlines()[-8:]
    lines = tail + (["[stderr]"] + err_tail if err_tail else [])
    reason = "超时" if result.timed_out else f"退出码 {result.exit_code}"
    return {
        "source": "harness",
        "summary": f"harness 没有交报告({reason})" + ("\n" + "\n".join(lines) if lines else ""),
        "steps": [],
        "counts": {},
        "exhausted": result.timed_out,
    }


def build_env(
    extra: dict[str, str] | None = None, tenant: str = ""
) -> dict[str, str]:
    """交给那条命令的环境变量。

    库里存的 harness-env 每个键都以大写注入;租户有自己的一份就用它,
    没有就落回公共值。调用方再给一份覆盖。
    凭据由平台注入,不由部署方进容器手配。
    """
    from engine.shared.config import config

    stored = {
        str(key).upper(): str(value)
        for key, value in config.get_scope_config("harness-env", tenant).items()
    }
    return {**stored, **(extra or {})}


async def run_harness(
    *,
    command: str,
    workspace: str | Path,
    task: str,
    extra_env: dict[str, str] | None = None,
    tenant: str = "",
    timeout_s: int = 1800,
) -> HarnessResult:
    """在工作区里跑一条命令,等它结束,读回报告。

    命令里的 {workspace} 会被替换成真实路径(容器里挂载要用);其余信息走环境变量,
    免得引号与转义在命令模板里打架。
    """
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    (root / "task.md").write_text(task, encoding="utf-8")
    report_path = root / REPORT_NAME

    resolved = command.replace("{workspace}", str(root))
    env = {**os.environ, **build_env(extra_env, tenant)}
    env.update(
        {
            "GWEI_WORKSPACE": str(root),
            "GWEI_REPORT": str(report_path),
            "GWEI_TASK_FILE": str(root / "task.md"),
        }
    )

    proc = await asyncio.create_subprocess_shell(
        resolved,
        cwd=str(root),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    timed_out = False
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        out, err = await proc.communicate()

    stdout = (out or b"").decode("utf-8", "replace")
    stderr = (err or b"").decode("utf-8", "replace")

    report = _read_report(root) or {}
    if report:
        report.setdefault("source", "harness")

    result = HarnessResult(
        report=report,
        exit_code=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        workspace=str(root),
    )
    if not report:
        result = HarnessResult(
            report=_fallback_report(result),
            exit_code=result.exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            workspace=str(root),
        )
    return result


__all__ = ["HarnessResult", "run_harness", "build_task", "build_env", "REPORT_NAME"]