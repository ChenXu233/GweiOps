# engine/harness/sandbox.py
"""沙箱 —— agent 在哪台机器上跑,平台只认这一个接口。

一次 harness 运行只有五件事,别的什么都不需要:

1. **把这一场的目录树送进去**:代码、任务书(`task.md`)、凭据(`.harness-env`)。
2. **认一下它还在不在**:云原生开发环境要先孵化、拿到地址才谈得上跑命令;
   本地命令拉起进程那一刻就已经在跑了。
3. **跑一条命令**:退出码、超时、输出。日志只是给人的,结论从报告来。
4. **把改动拿出来**:平台自己对着基线算,不听沙箱自报。
5. **说清它是怎么跑起来的**:一个能点开的地址、一个能查的编号。人在回评里
   看到的是"它在哪干的活",而不是"它说它干完了"。

**边界是提供者决定的,不是平台决定的。** 平台不知道 `docker run` 和 CNB 流水线
的区别,也不该知道:换一个地方跑,就是换一个提供者,`run_harness` 与出口一行不改。

三个实现已经写在这里:

- `local`  —— 一条命令,进程与工作区都在平台这台机器上。最弱,但是零依赖。
- `cnb`    —— CNB 的托管执行面(`cnb_sandbox.py`)。代码整包交进去,命令在它的
              容器里跑,日志与产物从 API 取回。文件系统是它的;cnb.cool 上的默认边界。
- `ssh`    —— 一个常开的会话(例如 CNB 云原生开发环境):平台持的是一把钥匙,
              不是一份字节流。地址在手,就不用每一场都重新孵一次。

接口带 `prepare / handshake / invoke / fetch / entries` 五个动作,是因为这五件事
在一场里必须分开:一次跑得长的命令不能占着一次握手的寿命,一次拿产物也不该
要求会话还活着。会话的生命周期归提供者管,平台只管"这一刻它还在不在"。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from . import blobs
from .adapter import REPORT_NAME, build_env
from .workspace import WorkspaceError

logger = logging.getLogger(__name__)

TASK_NAME = "task.md"


@dataclass(frozen=True)
class Entry:
    """一个沙箱提供者交回的一份东西。谁交的、能不能点开,由提供者自己说。"""

    provider: str  # local | cnb | ssh ...
    id: str = ""  # 会话编号 / 构建号 / 进程号,有什么给什么
    url: str = ""  # 人能点开看的地方(构建页、容器名)
    home: str = ""  # 这一场在沙箱里的目录
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """落到事故报告里的形状。空字段不写,免得界面上出现一排空表头。"""
        data: dict[str, Any] = {"provider": self.provider}
        for name in ("id", "url", "home"):
            value = getattr(self, name)
            if value:
                data[name] = value
        if self.extra:
            data["extra"] = dict(self.extra)
        return data


@dataclass(frozen=True)
class SandboxResult:
    """一场跑完的回音。`report` 是沙箱按约定交的那份,`output` 是它说过的话。"""

    report: dict[str, Any]
    exit_code: int | None = None
    output: str = ""
    error: str = ""
    timed_out: bool = False
    entry: Entry | None = None


@runtime_checkable
class Sandbox(Protocol):
    """一个执行环境的提供者。名字是一份部署里唯一的标识,也是配置里写的那个词。"""

    name: str

    async def prepare(self, *, workspace: Path, files: dict[str, bytes]) -> Any:
        """把这一场要的文件放进沙箱,返回一个句柄(下一次调用要用)。

        平台给的是字节 + 沙箱里的相对路径。怎么落进去(本地写盘 / 隔空会话写 /
        打包成一次构建的输入)是提供者的事,平台不猜。
        """
        ...

    async def handshake(self, handle: Any) -> bool:
        """这一刻它还是不是活的。返回 False 说明这一场要么还在孵、要么已经收了。"""
        ...

    async def invoke(
        self, handle: Any, *, command: str, env: dict[str, str], timeout_s: int
    ) -> SandboxResult:
        """在沙箱里跑一条命令,等它结束。"""
        ...

    async def fetch(self, handle: Any, paths: list[str]) -> dict[str, bytes]:
        """按路径把文件取回来。取不到的路径不放键 —— 空着就是空着,不编。"""
        ...

    async def entries(self, handle: Any) -> Entry:
        """这一场跑在哪:一个编号、一个地址。"""
        ...


class SandboxError(WorkspaceError):
    """沙箱没起来、跑不了、或者临时用不了。都带一句人能读的原因。"""


# ---------------------------------------------------------------------------
# local —— 一条命令,就在这台机器上
# ---------------------------------------------------------------------------


class LocalSandbox:
    """一条命令,进程与工作区都在平台这台机器上。

    这是最弱的一种:它只负责"跑起来",隔离靠命令自己(`docker run` / `ssh box`)。
    当初那版 `HARNESS_COMMAND` 就是它,换成提供者之后行为一字未变 ——
    已经配好的部署不会因为多了一层接口而换个跑法。
    """

    name = "local"

    async def prepare(self, *, workspace: Path, files: dict[str, bytes]) -> Path:
        workspace.mkdir(parents=True, exist_ok=True)
        # 工作区两边都要写:引擎写 task.md,沙箱写 report.json。两边的 uid 不一样
        # (引擎 gwei / 镜像里的 node),又改不动对方镜像,所以只放开这一层。
        try:
            os.chmod(workspace, 0o777)
        except OSError:  # 卷可能挂在只读的地方;那种情况报错留给下面那次写
            pass
        for name, data in files.items():
            target = workspace / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return workspace

    async def handshake(self, handle: Path) -> bool:
        return Path(handle).is_dir()

    async def invoke(
        self, handle: Path, *, command: str, env: dict[str, str], timeout_s: int
    ) -> SandboxResult:
        root = Path(handle)
        resolved = command.replace("{workspace}", str(root))
        proc = await asyncio.create_subprocess_shell(
            resolved,
            cwd=str(root),
            env={**os.environ, **env},
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

        report_path = root / REPORT_NAME
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
        return SandboxResult(
            report=report if isinstance(report, dict) else {},
            exit_code=proc.returncode,
            output=(out or b"").decode("utf-8", "replace"),
            error=(err or b"").decode("utf-8", "replace"),
            timed_out=timed_out,
            entry=Entry(provider=self.name, id=str(proc.pid), home=str(root)),
        )

    async def fetch(self, handle: Path, paths: list[str]) -> dict[str, bytes]:
        out: dict[str, bytes] = {}
        for path in paths:
            target = Path(handle) / path
            if target.is_file():
                out[path] = target.read_bytes()
        return out

    async def entries(self, handle: Path) -> Entry:
        return Entry(provider=self.name, id=str(handle), home=str(handle))


# ---------------------------------------------------------------------------
# ssh —— 一个常开的会话(CNB 云原生开发环境就是这种)
# ---------------------------------------------------------------------------


class SshSandbox:
    """一个常开的会话:地址与钥匙在手,就不用每一场都重新孵一次。

    代码由平台压成一份包 `scp` 上去,任务书与凭据单独落 —— 与 `cnb` 走的是同一
    份字节,只是搬运方式不同。

    **这把钥匙不是生产凭据**:它开的是沙箱。沙箱里能做的事仍然只有一件——
    调出口。改世界不靠它。
    """

    name = "ssh"

    def __init__(
        self,
        *,
        target: str,
        key_file: str = "",
        remote_root: str = "/tmp/gwei",
        ssh_options: str = "",
        scp_command: str = "scp",
        ssh_command: str = "ssh",
    ) -> None:
        if not target.strip():
            raise SandboxError("ssh 沙箱缺目标:写成 user@host 或者 ~/.ssh/config 里的别名")
        self.target = target.strip()
        self.key_file = key_file
        self.remote_root = remote_root.rstrip("/") or "/tmp/gwei"
        self.ssh_options = ssh_options
        self.scp_command = scp_command
        self.ssh_command = ssh_command

    def _opts(self) -> list[str]:
        opts = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
        if self.key_file:
            opts += ["-i", self.key_file]
        if self.ssh_options:
            opts += shlex.split(self.ssh_options)
        return opts

    def _home(self, handle: str) -> str:
        return f"{self.remote_root}/{handle}"

    async def _run(self, args: list[str], timeout_s: int = 120) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return -1, "", f"{args[0]} 超时({timeout_s}s)"
        return (
            int(proc.returncode or 0),
            (out or b"").decode("utf-8", "replace"),
            (err or b"").decode("utf-8", "replace"),
        )

    async def prepare(self, *, workspace: Path, files: dict[str, bytes]) -> str:
        handle = Path(workspace).name
        home = self._home(handle)
        code, _out, err = await self._run(
            [self.ssh_command, *self._opts(), self.target, f"mkdir -p {shlex.quote(home)}"]
        )
        if code != 0:
            raise SandboxError(f"连不上沙箱 {self.target}:{err.strip()[-300:]}")

        archive = blobs.pack(workspace)
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp.write(archive)
            local = tmp.name
        try:
            code, _out, err = await self._run(
                [self.scp_command, *self._opts(), local, f"{self.target}:{home}/workspace.tar.gz"],
                timeout_s=600,
            )
            if code != 0:
                raise SandboxError(f"代码送不进沙箱:{err.strip()[-300:]}")
        finally:
            Path(local).unlink(missing_ok=True)

        code, _out, err = await self._run(
            [
                self.ssh_command, *self._opts(), self.target,
                f"cd {shlex.quote(home)} && tar xzf workspace.tar.gz && rm -f workspace.tar.gz",
            ],
            timeout_s=600,
        )
        if code != 0:
            raise SandboxError(f"代码在沙箱里解不开:{err.strip()[-300:]}")

        if files:
            # 任务书与凭据单独写:它们不属于代码,不该跟着代码包走第二遍。
            # 一份文件一次 scp 落成临时文件,BatchMode 下不会有任何交互。
            for name, data in files.items():
                target = f"{home}/{name}"
                code, _out, err = await self._run(
                    [self.ssh_command, *self._opts(), self.target,
                     f"mkdir -p $(dirname {shlex.quote(target)})"]
                )
                if code != 0:
                    raise SandboxError(f"沙箱里建不出目录:{err.strip()[-300:]}")
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp.write(data)
                    local = tmp.name
                try:
                    code, _out, err = await self._run(
                        [self.scp_command, *self._opts(), local, f"{self.target}:{target}"],
                        timeout_s=120,
                    )
                finally:
                    Path(local).unlink(missing_ok=True)
                if code != 0:
                    raise SandboxError(f"{name} 写不进沙箱:{err.strip()[-300:]}")
        return handle

    async def handshake(self, handle: str) -> bool:
        code, _out, _err = await self._run(
            [self.ssh_command, *self._opts(), self.target, "true"], timeout_s=30
        )
        return code == 0

    async def invoke(
        self, handle: str, *, command: str, env: dict[str, str], timeout_s: int
    ) -> SandboxResult:
        """在会话里跑一条命令。环境变量随这条命令走,不落进会话的 shell 里。"""

        home = self._home(handle)
        exports = " ".join(f"{k}={shlex.quote(v)}" for k, v in sorted(env.items()))
        remote = (
            f"cd {shlex.quote(home)} && env {exports} {command}"
            if exports
            else f"cd {shlex.quote(home)} && {command}"
        )
        code, out, err = await self._run(
            [self.ssh_command, *self._opts(), self.target, remote], timeout_s=timeout_s
        )
        return SandboxResult(
            report={},
            exit_code=code,
            output=out,
            error=err,
            timed_out=code == -1 and "超时" in err,
            entry=Entry(provider=self.name, id=handle, url=f"ssh://{self.target}", home=home),
        )

    async def fetch(self, handle: str, paths: list[str]) -> dict[str, bytes]:
        """按路径把文件取回来。取不到就不放这个键 —— 空着就是空着,不编。"""

        home = self._home(handle)
        out: dict[str, bytes] = {}
        for path in paths:
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                local = tmp.name
            try:
                code, _out, _err = await self._run(
                    [self.scp_command, *self._opts(), f"{self.target}:{home}/{path}", local],
                    timeout_s=120,
                )
                if code == 0:
                    out[path] = Path(local).read_bytes()
            finally:
                Path(local).unlink(missing_ok=True)
        return out

    async def entries(self, handle: str) -> Entry:
        return Entry(
            provider=self.name, id=handle, url=f"ssh://{self.target}", home=self._home(handle)
        )


# ---------------------------------------------------------------------------
# 提供者表
# ---------------------------------------------------------------------------

# cnb 不在这里:它要参数,由 build_from_settings 按配置搭。这张表装的是"给个名字就能建"的。


def build_from_settings() -> Sandbox:
    """按配置搭出这个部署用的提供者。认不出来的名字,当场说清而不是等到开工。"""

    from engine.shared.config import config

    settings = config.settings
    kind = (settings.sandbox or "local").strip().lower()

    if kind == "local":
        return LocalSandbox()

    if kind == "ssh":
        return SshSandbox(
            target=settings.sandbox_ssh_target,
            key_file=settings.sandbox_ssh_key_file,
            remote_root=settings.sandbox_ssh_root,
            ssh_options=settings.sandbox_ssh_options,
        )

    if kind == "cnb":
        from .cnb_sandbox import CnbSandbox

        return CnbSandbox.from_settings()

    raise SandboxError(
        f"认不出这个沙箱:{kind!r};可选 local、cnb、ssh"
    )


__all__ = [
    "Entry",
    "LocalSandbox",
    "Sandbox",
    "SandboxError",
    "SandboxResult",
    "SshSandbox",
    "TASK_NAME",
    "build_from_settings",
    "blobs",
    "build_env",
    "REPORT_NAME",
]
