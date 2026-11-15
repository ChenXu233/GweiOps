# engine/harness/cnb_sandbox.py
"""CNB 托管执行面 —— 代码送进去,命令在它的容器里跑,产物取回来。

不用一种"隔着网络跑命令"的通道,原因很实在:

- **云开发环境没有免登通道**。`get-workspace-detail` 交回来的是一串 `ssh user@host`,
  没有凭据就一步也走不了;要让平台拿着一把钥匙连进去,那是另一个运维问题,
  而且每一场都要孵一次环境。这条路留着,但不在默认配置里。
- **`api_trigger` 构建没有这些问题**:令牌就是凭据,配置随请求走(不用往仓库里
  写 `.cnb.yml`),退出码、日志、编号都从 API 拿得到,而且它天然会把仓库的代码
  检出到 `/workspace`。

代价有一处,必须说清:**容器的文件系统是它的,不是平台的,而且跑完就没了。**
所以这一场的字节要来回一趟:

- 进去:平台把这一场的目录树压成一份包,`base64` 挂在环境变量里交进去;
- 出来:平台取回**改动过的文件**,在本地对着基线算出"改了哪些、多少行"。

"改了什么由平台数"这件事不能含糊:让沙箱自己数,平台就只能信一句话。所以
改动包是这条通道的必要组成部分,不是优化。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from . import blobs
from .adapter import REPORT_NAME
from .sandbox import Entry, SandboxError, SandboxResult

logger = logging.getLogger(__name__)

# 一次构建里,平台的产物落在哪。容器是干净的,这个目录只属于这一场。
INBOX = ".gwei"
# 挂在环境变量里交进去的上限。超过它就不是"省事",是给构建环境塞了一个大对象。
MAX_INLINE_BYTES = 96 * 1024 * 1024
# 代码进来、改动出去,两份包的名字。
CODE_ARCHIVE = "code.tar.gz"
CHANGES_ARCHIVE = "changes.tar.gz"

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# 日志行前面是 CNB 自己加的 "[+12ms  00:00:04] ";剥掉它,剩下的才是命令说的话。
_LOG_PREFIX = re.compile(r"^\[\s*[^\]]*\]\s?")

PENDING = "pending"


@dataclass
class CnbHandles:
    """这一场在 CNB 上的位置。构建号是唯一的把手,其余都是它的附属。"""

    sn: str
    pipeline_id: str = ""
    branch: str = ""
    repo: str = ""


def script(*, command: str, home: str, files: dict[str, str], env_names: list[str]) -> str:
    """构建里跑的那一小段 shell。

    它只做三件事:把平台交进来的包解开、把仓库那份代码摊进工作区、把命令要的
    环境变量备好。命令本身原样被调用,平台不替它解释。

    包从环境变量 (`$STAGE0`,base64 的 JSON) 来:`env` 里的 `$NAME` 会被 CNB 渲染成
    真实的值,这是唯一一条能把任意长度内容交进容器的路。`files` 是平台要单独
    落进去的几份(任务书、凭据),值是 **环境变量名**,不是内容。
    """

    lines = [
        "set -u",
        f"GWEI_HOME={shlex.quote(home)}",
        'mkdir -p "$GWEI_HOME"',
        'export GWEI_WORKSPACE="$GWEI_HOME/workspace"',
        'mkdir -p "$GWEI_WORKSPACE"',
        # CNB 自己检出的仓库在 /workspace:摊进平台的工作区,沙箱里就有代码了。
        # 已存在的文件不覆盖 —— 平台交进去的那份才是这一场的基线。
        'if [ -d /workspace ] && [ -n "$(ls -A /workspace 2>/dev/null)" ]; then '
        '(cd /workspace && tar -cf - . 2>/dev/null) | (cd "$GWEI_WORKSPACE" && tar -xf - '
        '--skip-old-files 2>/dev/null) || true; fi',
        'mkdir -p "$GWEI_HOME/.gwei"',
        'printf "%s" "$STAGE0" | base64 -d > "$GWEI_HOME/.stage0.json"',
        "python3 - <<'GWEI_STAGE0'",
        "import base64, json, pathlib, sys",
        'root = pathlib.Path(sys.argv[1])',
        'data = json.load(open(root / ".stage0.json", encoding="utf-8"))',
        "for name, value in data.items():",
        "    target = root / name",
        "    target.parent.mkdir(parents=True, exist_ok=True)",
        "    target.write_bytes(base64.b64decode(value))",
        'print("staged", len(data))',
        "GWEI_STAGE0",
        'rm -f "$GWEI_HOME/.stage0.json"',
        'chmod 600 "$GWEI_HOME/.harness-env" 2>/dev/null || true',
        'if [ -f "$GWEI_HOME/code.tar.gz" ]; then '
        'tar -xzf "$GWEI_HOME/code.tar.gz" -C "$GWEI_WORKSPACE" '
        '&& rm -f "$GWEI_HOME/code.tar.gz"; fi',
    ]
    if env_names:
        names = " ".join(shlex.quote(name) for name in env_names)
        lines.append(
            f'for name in {names}; do printf "%s=%s\\n" "$name" "${{!name:-}}" '
            '>> "$GWEI_HOME/.harness-env"; done'
        )
    lines.append('cd "$GWEI_WORKSPACE"')
    return "\n".join(lines)


def build_config(*, env_name: str, run_script: str, image: str, event: str) -> str:
    """这一次构建的流水线配置。

    随请求交上去(`config` 字段),不落到仓库里:平台要重跑一次时,配置得是
    "这一次"的样子,而不是某次提交时的样子。
    """

    return (
        "master:\n"
        f"  {event}:\n"
        "    - docker:\n"
        f"        image: {image}\n"
        "      env:\n"
        f"        STAGE0: ${env_name}\n"
        "      stages:\n"
        "        - name: gwei harness\n"
        "          script: |\n"
        + "\n".join(f"            {line}" for line in run_script.splitlines())
        + "\n"
    )


class CnbSandbox:
    """CNB 的托管执行面。一场 = 一次 `api_trigger` 构建。"""

    name = "cnb"

    def __init__(
        self,
        *,
        token: str,
        repo: str = "",
        branch: str = "",
        image: str = "cnbcool/default-npc:latest",
        event: str = "api_trigger_harness",
        base_url: str = "https://api.cnb.cool",
        poll_s: float = 5.0,
        home: str = "/tmp/gwei-harness",
        command: str = "",
        env_names: list[str] | None = None,
        handoff: Any = None,
        object_storage: CnbObjectStorage | None = None,
    ) -> None:
        if not token.strip():
            raise SandboxError("cnb 沙箱缺令牌:填 CNB_TOKEN(需要 repo-cnb-trigger:rw)")
        self.token = token.strip()
        self.repo = repo.strip()
        self.branch = branch.strip()
        self.image = image
        self.event = event
        self.base_url = base_url.rstrip("/")
        self.poll_s = poll_s
        self.home = home.rstrip("/") or "/tmp/gwei-harness"
        # 空 = 只把代码与任务书交进去,谁来做由镜像自己决定(CNB 的 NPC 角色)。
        self.command = command.strip()
        self.env_names = list(env_names or [])
        self.handoff = handoff
        self.object_storage = object_storage

    # -- 构造 ---------------------------------------------------------

    @classmethod
    def from_settings(cls) -> "CnbSandbox":
        from engine.shared.config import config

        settings = config.settings
        token = (settings.sandbox_cnb_token or "").strip()
        if not token:
            # 没有单独的沙箱令牌时,回落到 CNB 适配器里那份:它们打的是同一台 CNB。
            try:
                from plugins.builtin.adapters.cnb.config import CNBConfig

                token = CNBConfig().token
            except Exception:  # noqa: BLE001 - 适配器没装也不该让平台起不来
                token = ""
        return cls(
            token=token,
            repo=settings.sandbox_cnb_repo,
            branch=settings.sandbox_cnb_branch,
            image=settings.sandbox_cnb_image,
            event=settings.sandbox_cnb_event,
            base_url=settings.sandbox_cnb_base_url,
            poll_s=settings.sandbox_cnb_poll_s,
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    # -- 接口 ---------------------------------------------------------

    async def prepare(self, *, workspace: Path, files: dict[str, bytes]) -> CnbHandles:
        """把这一场送上去:一份构建配置 + 一份代码包 + 几份要落进去的文件。

        `handoff` 给了就交给它,由它决定这些字节怎么到那边去(第三方存储、平台
        自己的对象桶);没给就挂在环境变量里 —— `api_trigger` 的 `env` 支持任意
        长度的值,小仓库走这一条最省事。
        """

        if not self.repo:
            raise SandboxError("cnb 沙箱缺仓库:填 GWEI_SANDBOX_CNB_REPO(形如 org/repo)")

        stage: dict[str, str] = {}
        for name, data in files.items():
            stage[name] = base64.b64encode(data).decode("ascii")
        stage[f"{INBOX}/{CODE_ARCHIVE}"] = base64.b64encode(blobs.pack(workspace)).decode("ascii")

        if self.handoff is None and len(json.dumps(stage)) > MAX_INLINE_BYTES:
            raise SandboxError(
                "这一场的代码太大,挂在环境变量里交不进去;"
                "配上 object_storage(第三方存储)走整包上传这条路"
            )

        env: dict[str, str] = {}
        if self.handoff is None:
            env["STAGE0"] = base64.b64encode(json.dumps(stage).encode("utf-8")).decode("ascii")
        else:
            env["STAGE0"] = await self.handoff.handoff(stage)

        run_script = script(
            command=self.command,
            home=self.home,
            files={name: "STAGE0" for name in files},
            env_names=list(self.env_names),
        )
        body: dict[str, Any] = {
            "event": self.event,
            "config": build_config(
                env_name="STAGE0", run_script=run_script, image=self.image, event=self.event
            ),
            "env": env,
        }
        if self.branch:
            body["branch"] = self.branch

        data = await self._request("POST", f"/{self.repo}/-/build/start", json=body)
        sn = str(data.get("sn") or "")
        if not sn:
            raise SandboxError(f"CNB 没给出构建号:{data}")
        logger.info("cnb sandbox %s: %s", sn, data.get("buildLogUrl") or "")
        return CnbHandles(sn=sn, branch=self.branch, repo=self.repo)

    async def handshake(self, handle: CnbHandles) -> bool:
        """构建到终态了没有。没到就是还在跑。"""
        try:
            data = await self._request("GET", f"/{self.repo}/-/build/status/{handle.sn}")
        except SandboxError:
            return False
        status = str(data.get("status") or "")
        return status not in ("", PENDING, "running", "start")

    async def invoke(
        self, handle: CnbHandles, *, command: str, env: dict[str, str], timeout_s: int
    ) -> SandboxResult:
        """等这一场跑完,再把它的日志读回来当输出。"""

        deadline = asyncio.get_event_loop().time() + timeout_s
        status = PENDING
        while asyncio.get_event_loop().time() < deadline:
            data = await self._request("GET", f"/{self.repo}/-/build/status/{handle.sn}")
            status = str(data.get("status") or "")
            if status and status not in (PENDING, "running", "start"):
                pipeline = (data.get("pipelinesStatus") or {})
                if pipeline:
                    handle.pipeline_id = str(next(iter(pipeline)))
                break
            await asyncio.sleep(self.poll_s)
        else:
            return SandboxResult(
                report={},
                exit_code=None,
                error=f"等了 {timeout_s}s 还没跑完({status})",
                timed_out=True,
                entry=await self.entries(handle),
            )

        output = await self._log(handle)
        return SandboxResult(
            report={},
            exit_code=0 if status == "success" else 1,
            output=output,
            error="" if status == "success" else f"构建 {status}",
            timed_out=False,
            entry=await self.entries(handle),
        )

    async def fetch(self, handle: CnbHandles, paths: list[str]) -> dict[str, bytes]:
        """把这一场的产物取回来。

        只取平台认得的两个位置:`report.json` 与改动包。其余东西再怎么取也没有
        第二个人看,不如不取 —— 少一次搬运就少一次"它在沙箱外动了什么"的机会。
        """

        out: dict[str, bytes] = {}
        report = await self._file(handle, f"{INBOX}/{REPORT_NAME}")
        if report is not None and REPORT_NAME in paths:
            out[REPORT_NAME] = report
        archive = await self._file(handle, f"{INBOX}/{CHANGES_ARCHIVE}")
        if archive is not None:
            out[CHANGES_ARCHIVE] = archive
        return out

    async def entries(self, handle: CnbHandles) -> Entry:
        return Entry(
            provider=self.name,
            id=handle.sn,
            url=f"https://cnb.cool/{self.repo}/-/build/logs/{handle.sn}",
            home=f"{self.home}/workspace",
            extra={"event": self.event, "repo": self.repo},
        )

    # -- 与 CNB 说话 ---------------------------------------------------

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.request(method, url, headers=self._headers(), **kwargs)
        if response.status_code >= 400:
            raise SandboxError(
                f"CNB {path} 返回 {response.status_code}:{response.text[:300]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise SandboxError(f"CNB {path} 回的不是 JSON:{exc}") from exc

    async def _log(self, handle: CnbHandles) -> str:
        """构建日志。剥掉时间戳与颜色码,剩下的才是这一场里命令说了什么。"""

        if not handle.pipeline_id:
            data = await self._request("GET", f"/{self.repo}/-/build/status/{handle.sn}")
            pipelines = data.get("pipelinesStatus") or {}
            if pipelines:
                handle.pipeline_id = str(next(iter(pipelines)))
        if not handle.pipeline_id:
            return ""
        url = f"{self.base_url}/{self.repo}/-/build/logs/{handle.pipeline_id}/download"
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.get(url, headers=self._headers())
        if response.status_code >= 400:
            return ""
        text = _ANSI.sub("", response.text)
        lines = []
        for line in text.splitlines():
            stripped = _LOG_PREFIX.sub("", line)
            if stripped.strip():
                lines.append(stripped)
        return "\n".join(lines)

    async def _file(self, handle: CnbHandles, name: str) -> bytes | None:
        """产物取回。

        构建容器是临时的,跑完就没了;CNB 的构建产物也不在本仓库的制品库里。
        所以产物必须先落到一个两边都够得着的地方:那就是 `object_storage`。
        没配的时候如实返回空 —— 不假装取到了,也不悄悄把"没交报告"说成"跑完了"。
        """

        if self.object_storage is None:
            logger.info("cnb %s: 没配 object_storage,%s 取不回来", handle.sn, name)
            return None
        key = f"{handle.sn}/{name}"
        return await self.object_storage.get(key)


class CnbObjectStorage:
    """两边的公共中转:签名地址由平台出,沙箱按地址 PUT 产物。

    平台只签两个键(报告、改动包),沙箱也只往这两个键里放东西。桶里还留着
    别人写的别的对象不要紧:平台不列桶,只取自己签过的那两个。
    """

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        prefetch_url: str = "",
        access_key: str = "",
        secret_key: str = "",
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.bucket = bucket.strip("/")
        self.prefetch_url = prefetch_url.rstrip("/")
        self.access_key = access_key
        self.secret_key = secret_key

    async def put(self, key: str, data: bytes) -> str:
        """平台自己往桶里放一份(交进去的包走这条路)。返回一个沙箱够得着的地址。"""

        url = f"{self.endpoint}/{self.bucket}/{key}"
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.put(url, content=data)
        if response.status_code >= 400:
            raise SandboxError(f"对象存储 PUT 失败({response.status_code}):{response.text[:200]}")
        return f"{self.prefetch_url}/{key}"

    async def get(self, key: str) -> bytes | None:
        url = f"{self.endpoint}/{self.bucket}/{key}"
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.get(url)
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise SandboxError(
                f"对象存储 GET 失败({response.status_code}):{response.text[:200]}"
            )
        return response.content


__all__ = [
    "CHANGES_ARCHIVE",
    "CnbObjectStorage",
    "CODE_ARCHIVE",
    "CnbHandles",
    "CnbSandbox",
    "INBOX",
    "MAX_INLINE_BYTES",
    "build_config",
    "script",
]
