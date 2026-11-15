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
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .sandbox import Sandbox

logger = logging.getLogger(__name__)

REPORT_NAME = "report.json"
# harness 要用到的环境变量也落一份在盘上:命令里逐个 -e 点名太容易漏,
# docker 的 --env-file 一次就能全带进去。它是引擎写的(docker CLI 在引擎这一侧
# 读),所以权限收到 0600,容器里那个用户反而看不见这个文件。
ENV_FILE_NAME = ".harness-env"


@dataclass(frozen=True)
class HarnessResult:
    report: dict[str, Any]
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    workspace: str = ""
    entry: Any = None  # 这一场跑在哪;形状见 sandbox.Entry


def build_task(
    *,
    incident_id: str,
    signal: dict[str, Any],
    exit_url: str,
    workspace: str,
    report_path: str,
    repo: str = "",
    branch: str = "",
    token: str = "",
    thread: dict[str, Any] | None = None,
) -> str:
    """交给 harness 的任务文本。它自己决定怎么查、怎么改,这里只说清楚边界。"""
    detail = str(signal.get("detail") or "").strip()
    title = signal.get("title") or signal.get("subject") or "(未命名)"
    from_github = signal.get("source") == "github"

    lines = [
        "有人在这个仓库里提了一个改动需求:改代码并开一个 PR。"
        if from_github
        else "你在处理一次线上事故。",
        "",
        f"事故编号:{incident_id}",
        f"{'需求' if from_github else '信号'}:{title}",
    ]
    if repo:
        lines.append(f"仓库:{repo}" + (f"(基线分支 {branch})" if branch else ""))
    if detail:
        lines.append(f"详情:{detail}")

    if repo:
        lines += [
            "",
            f"工作区的 {workspace} 里是 {repo} 这份代码的当前内容。没有 .git:提交、分支、PR",
            "都由平台做,你不要自己 git push,也没有可用的凭据。改文件就行,改完可以让它变成",
            "一个 PR——那是出口里的 pr.open,一次调用就是一个可撤销的变更单元。",
            "pr.open 的 files 不用你填:平台会读工作区里你改过的文件,paths 只在你想只交一部分",
            "文件时才给。repo 和 head 必须自己给:repo 就是上面那个仓库名,head 是分支名",
            "(例如 gwei/add-settings-page);base 不用给,缺省就是仓库的默认分支。",
            "一次需求开一个 PR,不要开第二个。",
            "",
            "改动通常只占几行:在原文件里插入,不要整篇重写,不要删掉你以为不重要的段落。",
        ]
        if thread and thread.get("head"):
            lines += [
                "",
                f"这个话题上已经有一个打开的 PR:#{thread.get('pull') or '?'}"
                f"(分支 {thread['head']})。",
                f"接着它改:pr.open 的 head 就用 {thread['head']},平台会把这次提交追加到"
                "那个 PR 上,不会另外再开一个。",
            ]
    else:
        lines.append(f"\n工作区在 {workspace}。随便用:读代码、跑测试、改文件都行。")

    lines += [
        "",
        "改变外部世界只能通过出口(每次调用都经过平台判定,可能被拒绝或撤销,",
        "被拒绝时 reason 会写明原因;不要对同一个动作反复试):",
        f"  GET  {exit_url}",
        f"  POST {exit_url}/<能力名>",
        "  GET 时会告诉你这个部署里能做什么、每个动作要哪些参数。",
    ]
    if token:
        # 认证方式必须写在纸面上:让 agent 去猜 401 该怎么办,它只会把时间花在翻环境上。
        lines += [
            "",
            "这两个地址要带请求头,值就是下面这一串:",
            f"  X-Gwei-Token: {token}",
            "例如:",
            f'  curl -s -H "X-Gwei-Token: {token}" {exit_url}',
        ]
    lines += [
        "",
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
    """没交报告也要有个交代。

    退出码是 0 说明它干完了,只是没按约定写 report.json —— 那种情况下它的输出就是
    答案,原样带回来,别把一句"没交报告"当成人读的结论(那会把一段正常的工作描述成
    失败)。非零退出码才是失败:那时带退出码与最后几行输出,stderr 也带上——dsh 这类
    启动器把失败原因写在 stderr,只看 stdout 等于把「为什么没跑起来」丢掉。
    """
    # [plan] 是启动脚本自己的话,不是 agent 说的
    out = [
        line
        for line in (result.stdout or "").strip().splitlines()
        if line.strip() and not line.startswith("[plan]")
    ]
    answer = "\n".join(out[-12:]).strip()

    if result.exit_code == 0 and not result.timed_out and answer:
        return {
            "source": "harness",
            "summary": answer,
            "steps": [],
            "counts": {},
            "exhausted": False,
            # 约定没被遵守这件事要留痕,但不必占用"人读的第一行"
            "report_missing": True,
        }

    err_tail = (result.stderr or "").strip().splitlines()[-8:]
    lines = out[-8:] + (["[stderr]"] + err_tail if err_tail else [])
    reason = "超时" if result.timed_out else f"退出码 {result.exit_code}"
    return {
        "source": "harness",
        "summary": f"agent 没跑完({reason})" + ("\n" + "\n".join(lines) if lines else ""),
        "steps": [],
        "counts": {},
        "exhausted": result.timed_out,
        "report_missing": True,
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


def env_file_text(values: dict[str, str]) -> str:
    """docker --env-file 与沙箱里那份 `.harness-env` 共用的写法。

    带换行的值(整段 PEM)写不进去,跳过 —— 那种东西该走 -e 或者挂文件,不该塞进
    env 文件里假装成功。
    """
    usable = {
        str(key): str(value)
        for key, value in values.items()
        if str(value) and "\n" not in str(value) and "\r" not in str(value)
    }
    return "".join(f"{k}={v}\n" for k, v in sorted(usable.items()))


def _write_env_file(root: Path, values: dict[str, str]) -> Path:
    """把这一场要用的环境变量写成 docker --env-file 能读的样子。"""

    path = root / ENV_FILE_NAME
    path.write_text(env_file_text(values), encoding="utf-8")
    try:
        os.chmod(path, 0o600)  # 只有引擎这一侧要读它(docker CLI 在引擎里)
    except OSError:
        pass
    return path


async def run_harness(
    *,
    command: str,
    workspace: str | Path,
    task: str,
    extra_env: dict[str, str] | None = None,
    tenant: str = "",
    timeout_s: int = 1800,
    sandbox: "Sandbox | None" = None,
    checkout_repo: str | Path | None = None,
) -> HarnessResult:
    """把这一场交给沙箱,拿回一份报告。

    五步,与"在哪跑"无关:`prepare` 交进去 → `handshake` 认一下 → `invoke` 跑
    → `fetch` 取产物 → 平台自己对着基线算改动。换一个地方跑,只换 `sandbox`。

    `command` 里的 `{workspace}` 会被替换成沙箱里的目录。`checkout_repo` 给了
    才算得出"它改了哪些文件"—— 算不出来的时候,出口也不会拿一份凭空的改动去开 PR。
    """

    from . import blobs as blobs_mod
    from . import sandbox as sandbox_mod
    from .sandbox import Entry

    provider: Sandbox = sandbox or sandbox_mod.LocalSandbox()
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)

    harness_env = build_env(extra_env, tenant)
    (root / "task.md").write_text(task, encoding="utf-8")
    report_path = root / REPORT_NAME
    # 告诉 agent 报告落在哪:local 是这台机器上的绝对路径,别的沙箱是相对目录。
    env_report = report_path if provider.name == "local" else REPORT_NAME

    # 沙箱里的路径由提供者定,这里给的是"这一场"的名字,不是宿主机路径:
    # 同一个 task.md 在 local 是绝对路径,在 CNB 是容器里的另一处,agent 不必知道。
    # 与机器无关的那几项从 extra_env 来 —— 它们本来就是"这一场"的事实。
    env = {
        **(extra_env or {}),
        **harness_env,
        "GWEI_REPORT": env_report,
        "GWEI_TASK_FILE": "task.md",
    }

    files: dict[str, bytes] = {
        "task.md": task.encode("utf-8"),
        ENV_FILE_NAME: env_file_text(harness_env).encode("utf-8"),
    }

    try:
        handle = await provider.prepare(workspace=root, files=files)
    except Exception as exc:  # noqa: BLE001 - 起不来也是一种要人看的结论
        return HarnessResult(
            report=_fallback_report(
                HarnessResult(report={}, exit_code=None, stderr=f"{type(exc).__name__}: {exc}")
            ),
            exit_code=None,
            stderr=f"{type(exc).__name__}: {exc}",
            workspace=str(root),
            entry=Entry(provider=provider.name),
        )

    try:
        await provider.handshake(handle)
    except Exception:  # noqa: BLE001 - 认一下失败不该让这一场直接死,run 会自己说
        logger.warning("sandbox handshake failed", exc_info=True)

    result = await provider.invoke(
        handle, command=command.replace("{workspace}", str(root)), env=env, timeout_s=timeout_s
    )

    fetched: dict[str, bytes] = {}
    try:
        fetched = await provider.fetch(handle, [REPORT_NAME, blobs_mod.CHANGES_ARCHIVE])
    except Exception as exc:  # noqa: BLE001 - 取不回来就是没有,别让它盖掉 run 的结论
        logger.warning("sandbox fetch failed: %s", exc)

    report = _report_from(fetched, result)
    if report:
        report.setdefault("source", "harness")

    entry = result.entry
    if entry is None:
        try:
            entry = await provider.entries(handle)
        except Exception:  # noqa: BLE001
            entry = Entry(provider=provider.name)

    if checkout_repo is not None:
        await _bring_changes(Path(checkout_repo), root, fetched.get(blobs_mod.CHANGES_ARCHIVE))

    final = HarnessResult(
        report=report,
        exit_code=result.exit_code,
        stdout=result.output,
        stderr=result.error,
        timed_out=result.timed_out,
        workspace=str(root),
        entry=entry,
    )
    if not report:
        final = HarnessResult(
            report=_fallback_report(final),
            exit_code=final.exit_code,
            stdout=final.stdout,
            stderr=final.stderr,
            timed_out=final.timed_out,
            workspace=final.workspace,
            entry=entry,
        )
    return final


def _report_from(fetched: dict[str, bytes], result: HarnessResult) -> dict[str, Any]:
    """报告有两个来源:沙箱直接交的,或者跟着改动包回来的。"""

    raw = fetched.get(REPORT_NAME)
    if raw is None and result.report:
        return dict(result.report)
    if raw is None:
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


async def _bring_changes(repo: Path, workspace: Path, archive: bytes | None) -> None:
    """把沙箱里的改动落到本地工作区,好让"改了哪些、多少行"由平台自己数。

    取不到包就不落:本地工作区保持原样,`diff_stat` 说的就是"没有改动"——
    那是对的,平台确实没看见任何改动。
    """

    if not archive:
        return
    from . import blobs, workspace as ws

    try:
        files = blobs.read_changes(archive)
    except ws.WorkspaceError as exc:
        logger.warning("改动包读不出来: %s", exc)
        return
    for item in files:
        path = str(item.get("path") or "")
        if not path:
            continue
        target = workspace / path
        try:
            ws._inside(workspace, path)  # noqa: SLF001 - 同一个包,同一条路径规则
        except ws.WorkspaceError:
            logger.warning("改动包里有跑出工作区的路径: %s", path)
            continue
        if item.get("delete"):
            target.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(item.get("content") or ""), encoding="utf-8")


__all__ = [
    "HarnessResult",
    "run_harness",
    "build_task",
    "build_env",
    "env_file_text",
    "ENV_FILE_NAME",
    "REPORT_NAME",
]
