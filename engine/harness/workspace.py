# engine/harness/workspace.py
"""工作区里的代码 —— 从哪来,改了什么,怎么读出来。

把改动变成提交、分支、PR 是平台这一侧的事,所以容器里不需要 git 凭据。平台
于是要做三件事:

1. **开工前放进代码**:用 App 安装令牌走 `http.extraheader` 拉一次,令牌只在那一条
   命令里,不落进 `.git/config`,也不进容器。
2. **仓库那份留在工作区外面**(工作区根下的 `.repos/<incident>`)。从此处看,容器只
   挂得到事故那一个子目录,看不到 `.git`:既不会因为 uid 不同报 dubious ownership,
   也没有把凭据用出去的机会。
3. **收工时对照着读**:`git --git-dir=… --work-tree=… status` 说清改了哪些路径,内容
   由平台读。agent 不用把整份文件塞进出口参数——那既容易截断,也让人看不出它到底
   动过哪些文件。

铺进工作区的那份不带 `.git`,并放开到其他用户可写:引擎是 gwei(999),harness 镜像
里是 node(1000),不放宽就一个文件都改不动。
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 一次提交能带多少:多到这个数的改动不是"改一下",该拆成几次。
MAX_FILES = 100
# 单文件上限。GitHub 的 blob API 给的是 100 MB,这里卡得小得多——超过这个体积的
# 东西多半是资源或构建产物,不该由一个读文件的出口悄悄提交。
MAX_FILE_BYTES = 512 * 1024

# 工作区里属于平台自己、不属于这次改动的文件。
# .harness-env 里是这一场的凭据,跟着提交走就等于把它们写进仓库。
IGNORED_NAMES = {"task.md", "report.json", ".harness-env"}

REPO_DIR = ".repos"

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class WorkspaceError(ValueError):
    """工作区没准备好,或者改动读不出来。"""


@dataclass(frozen=True)
class Checkout:
    """一份代码:仓库副本在哪、基线是哪条分支的哪个提交。"""

    repo_path: Path
    branch: str
    commit: str


def safe_id(incident_id: str) -> str:
    """事故编号会拼进路径,所以只能由它自己决定不了的东西组成。"""
    if not _SAFE_ID.match(incident_id or ""):
        raise WorkspaceError(f"事故编号不能当目录名用:{incident_id!r}")
    return incident_id


def workspace_of(root: str | Path, incident_id: str) -> Path:
    """harness 看得见、改得动的那一层。"""
    return Path(root) / safe_id(incident_id)


def repo_of(root: str | Path, incident_id: str) -> Path:
    """平台自己留着的那份仓库副本:在工作区外面,容器挂不到。"""
    return Path(root) / REPO_DIR / safe_id(incident_id)


async def _git(*args: str, cwd: Path | None = None, timeout_s: int = 300) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise WorkspaceError(f"git {args[0]} 超时({timeout_s}s)") from None
    if proc.returncode != 0:
        detail = (err or b"").decode("utf-8", "replace").strip()[-400:]
        raise WorkspaceError(f"git {args[0]} 失败(退出码 {proc.returncode}):{detail}")
    return (out or b"").decode("utf-8", "replace")


async def clone(*, url: str, token: str, branch: str, dest: Path) -> Checkout:
    """拉一份浅克隆。令牌只在这一次命令行里。"""
    if dest.exists():
        # 重跑就重来:上一次留下了什么(半拉下来的 .git)不值得猜。
        shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)

    args: list[str] = []
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        # 走 -c 而不是写进 URL:URL 会留在 .git/config 和 ps 里,-c 只活在这次进程。
        args += ["-c", f"http.extraheader=Authorization: Basic {basic}"]
    args += ["clone", "--depth", "1", "--no-tags"]
    if branch:
        args += ["--branch", branch]
    args += [url, str(dest)]
    await _git(*args)

    sha = (await _git("-C", str(dest), "rev-parse", "HEAD")).strip()
    # 远端地址留成干净的那种:这个副本是平台的,不该记住任何凭据。
    await _git("-C", str(dest), "remote", "set-url", "origin", url)
    return Checkout(repo_path=dest, branch=branch, commit=sha)


def open_up(root: Path) -> None:
    """目录可进可写,文件可读可写;原本可执行的文件保持可执行。

    Windows 上 chmod 只表达只读位,这里不做兼容处理:容器里跑的是 Linux。
    """

    for base, _dirs, files in os.walk(root):
        try:
            os.chmod(base, 0o777)
        except OSError:
            continue
        for name in files:
            path = os.path.join(base, name)
            try:
                mode = os.stat(path).st_mode
                os.chmod(path, 0o777 if mode & 0o111 else 0o666)
            except OSError:
                continue


def materialize(checkout: Checkout, workspace: Path) -> None:
    """把代码铺进工作区:不带 .git,权限放开。

    先清空:上一次的残留(哪怕只是 report.json)会让"这次改了哪些文件"变得不可信。
    """

    workspace.mkdir(parents=True, exist_ok=True)
    for entry in list(workspace.iterdir()):
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            try:
                entry.unlink()
            except OSError:
                pass

    for entry in checkout.repo_path.iterdir():
        if entry.name == ".git":
            continue
        target = workspace / entry.name
        if entry.is_dir() and not entry.is_symlink():
            shutil.copytree(entry, target, symlinks=True)
        else:
            shutil.copy2(entry, target, follow_symlinks=False)

    open_up(workspace)


async def prepare(
    *, source: dict[str, Any], root: str | Path, incident_id: str
) -> Checkout:
    """开工前的一步:拉代码、铺进工作区。

    source 由适配器给(地址、令牌、基线分支);平台不认识 GitHub,只认这三个字段。
    """

    checkout = await clone(
        url=str(source.get("url") or ""),
        token=str(source.get("token") or ""),
        branch=str(source.get("branch") or ""),
        dest=repo_of(root, incident_id),
    )
    materialize(checkout, workspace_of(root, incident_id))
    return checkout


def _ignored(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name in IGNORED_NAMES


def _inside(workspace: Path, path: str) -> Path:
    """工作区里的相对路径,不许跑出去。"""
    if not path or path.startswith("/") or "\\" in path:
        raise WorkspaceError(f"只接受工作区里的相对路径:{path!r}")
    root = workspace.resolve()
    target = (root / path).resolve()
    if target != root and root not in target.parents:
        raise WorkspaceError(f"这个路径跑出工作区了:{path!r}")
    return target


def _read(workspace: Path, path: str) -> dict[str, Any]:
    target = _inside(workspace, path)
    if not target.exists():
        raise WorkspaceError(f"工作区里没有这个文件:{path}")
    data = target.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise WorkspaceError(
            f"{path} 有 {len(data) // 1024} KB,超过单文件上限 {MAX_FILE_BYTES // 1024} KB;"
            "这种体积的改动该拆成几次提交,或者由人来做"
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise WorkspaceError(f"{path} 不是 UTF-8 文本,这个出口只提交文本文件") from None
    return {"path": path, "content": text}


async def changed_paths(checkout_repo: Path, workspace: Path) -> dict[str, str]:
    """工作区相对基线提交的改动:路径 → 工作区状态码(空字符串表示未改动)。"""

    out = await _git(
        "--git-dir",
        str(checkout_repo / ".git"),
        "--work-tree",
        str(workspace),
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--no-renames",
        cwd=workspace,
    )
    changes: dict[str, str] = {}
    for record in out.split("\0"):
        if len(record) < 4:
            continue
        changes[record[3:]] = record[:2]
    return changes


async def collect(
    checkout_repo: Path, workspace: Path, paths: list[str] | None = None
) -> list[dict[str, Any]]:
    """把工作区里的改动读成提交能用的形状。

    paths 给了就只要那几个;没给就全都要——名单越短越容易漏,平台自己能算,
    就不该让 agent 去记它改过哪几个文件。
    """

    if not (checkout_repo / ".git").exists():
        raise WorkspaceError("这一场没有仓库副本,读不出改动")

    changes = {
        path: status
        for path, status in (await changed_paths(checkout_repo, workspace)).items()
        if not _ignored(path)
    }

    files: list[dict[str, Any]] = []
    if paths:
        wanted = [str(p) for p in paths]
        for path in wanted:
            status = changes.get(path)
            if status is not None and "D" in status:
                files.append({"path": path, "delete": True})
                continue
            files.append(_read(workspace, path))
    else:
        for path, status in sorted(changes.items()):
            if "D" in status:
                files.append({"path": path, "delete": True})
                continue
            files.append(_read(workspace, path))

    if not files:
        raise WorkspaceError(
            "工作区里没有改动:改完文件再开 PR,或者确认路径对不对"
        )
    if len(files) > MAX_FILES:
        raise WorkspaceError(
            f"这次改动了 {len(files)} 个文件,超过单次上限 {MAX_FILES};拆成几次提交"
        )
    return files


__all__ = [
    "Checkout",
    "MAX_FILE_BYTES",
    "MAX_FILES",
    "WorkspaceError",
    "changed_paths",
    "clone",
    "collect",
    "materialize",
    "open_up",
    "prepare",
    "repo_of",
    "safe_id",
    "workspace_of",
]
