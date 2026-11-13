# plugins/builtin/actions/docker-compose/plugin.py
"""docker compose 动作插件 —— 变更单元契约的第一个下游样例。

可逆性来自对称操作:把副本数缩回去,不需要下游保留任何旧状态。
因此窗口不是时长,而是"compose 项目还在就还能缩回去"(unbounded)。

平台不假设与本机同机:插件由 binding 决定打到哪个 docker daemon,
binding="local" 是本机 socket,其余值作为 -H 目标(ssh:// 或 tcp://)。
插件应当部署在目标环境内;跨环境直连只是过渡形态。

命令行调用经 ctor 注入,测试不需要 docker 守护进程。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable

from engine.change_unit import Effect, EffectNotApplied, Window
from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType

COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
LOCAL_BINDING = "local"
# compose 文件用 ${GWEI_RELEASE_IMAGE} 取这次要发布的镜像;插件把目标镜像经环境变量传进去。
DEFAULT_IMAGE_ENV = "GWEI_RELEASE_IMAGE"

Runner = Callable[..., str]


def run_compose(args: list[str], cwd: str, env: dict[str, str] | None = None) -> str:
    """真实调用 docker compose。只有它碰外部世界。"""
    proc = subprocess.run(
        ["docker", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ, **env} if env else None,
    )
    return proc.stdout


class DockerComposeAction(PluginBase):
    def __init__(
        self,
        runner: Runner | None = None,
        binding: str = LOCAL_BINDING,
        tenant: str = "",
        image_env: str = DEFAULT_IMAGE_ENV,
    ) -> None:
        self._dir = Path(__file__).parent
        self._run = runner or run_compose
        self.binding = binding
        self.tenant = tenant
        # 发布时把镜像名塞进这个环境变量;compose 文件通过它决定跑哪个镜像。
        self.image_env = image_env

    # -- 清单元数据 -------------------------------------------------

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="docker-compose",
            version="0.1.0",
            type=PluginType.ACTION,
            description="用 docker compose 执行可撤销的服务变更",
            capabilities=["compose.scale", "compose.release"],
        )

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass

    # 效果声明的解释权在核心(registry.effect_decl),插件只负责执行。

    async def health_check(self) -> bool:
        return True

    async def handle_event(self, event: str, data: dict[str, Any]) -> dict[str, Any]:
        return {"status": "ignored"}

    # -- 任务分发 ---------------------------------------------------

    async def execute_task(self, task: str, params: dict[str, Any]) -> dict[str, Any]:
        if task == "scale":
            return await self._scale(params)
        if task == "undo_scale":
            return await self._undo_scale(params)
        if task == "release":
            return await self._release(params)
        if task == "undo_release":
            return await self._undo_release(params)
        if task == "window":
            return await self.window(params["effect"], params.get("handle"))
        if task == "verify":
            ok, facts = await self.verify(params["effect"], params["handle"])
            return {"ok": ok, "facts": facts}
        return {"status": "error", "message": f"Unknown task: {task}"}

    # -- provider 协议 ----------------------------------------------

    async def execute(self, task: str, args: dict[str, Any]) -> dict[str, Any]:
        return await self.execute_task(task, args)

    async def undo(self, task: str, args: dict[str, Any], handle: str) -> dict[str, Any]:
        return await self.execute_task(task, {"handle": handle})

    async def window(self, effect: Effect, handle: str | None) -> Window:
        project_dir = effect.args.get("project_dir")
        if not project_dir:
            return Window(source="no project_dir")
        if self._compose_file(project_dir) is None:
            return Window(source="compose 文件不存在")
        return Window(unbounded=True, source="project_present")

    async def verify(self, effect: Effect, handle: str) -> tuple[bool, dict[str, Any]]:
        state = json.loads(handle)
        rows = await self._ps(state["project_dir"], state["compose_file"])
        running = self._running(rows, state["service"])
        if effect.capability == "compose.release":
            images = [
                str(row.get("Image") or "")
                for row in rows
                if row.get("Service") == state["service"]
            ]
            matched = any(self._same_image(image, state["target_image"]) for image in images)
            facts = {
                "running": running,
                "image": images[0] if images else "",
                "target_image": state["target_image"],
                "service": state["service"],
            }
            return running >= 1 and matched, facts
        facts = {"running": running, "target": state["target"], "service": state["service"]}
        return running >= state["target"], facts

    # -- 实现 -------------------------------------------------------

    def _host_args(self) -> list[str]:
        if self.binding == LOCAL_BINDING:
            return []
        return ["-H", self.binding]

    def _compose_file(self, project_dir: str) -> Path | None:
        for name in COMPOSE_FILES:
            candidate = Path(project_dir) / name
            if candidate.is_file():
                return candidate
        return None

    async def _exec(
        self, args: list[str], cwd: str, env: dict[str, str] | None = None
    ) -> str:
        """跑一条 docker compose 命令;env 只在发布时需要。

        测试里的 runner 只实现 (args, cwd):没 env 时保持老签名,别为了一个
        新效果把所有替身都改一遍。
        """
        if env:
            return await asyncio.to_thread(self._run, args, cwd, env)
        return await asyncio.to_thread(self._run, args, cwd)

    @staticmethod
    def _image_of(rows: list[dict[str, Any]], service: str) -> str:
        for row in rows:
            if row.get("Service") != service:
                continue
            state = str(row.get("State", "")).lower()
            status = str(row.get("Status", "")).lower()
            if state == "running" or status.startswith("up"):
                return str(row.get("Image") or "")
        return ""

    @staticmethod
    def _same_image(left: str, right: str) -> bool:
        """镜像名可能带 registry 前缀;同一个镜像不该因为写法不同判成失败。"""
        if not left or not right:
            return False
        return left == right or left.endswith("/" + right) or right.endswith("/" + left)

    async def _ps(self, project_dir: str, compose_file: str) -> list[dict[str, Any]]:
        out = await asyncio.to_thread(
            self._run,
            [*self._host_args(), "compose", "-f", compose_file, "ps", "--format", "json"],
            project_dir,
        )
        return self._parse_ps(out)

    @staticmethod
    def _parse_ps(out: str) -> list[dict[str, Any]]:
        text = out.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        return data if isinstance(data, list) else [data]

    @staticmethod
    def _running(rows: list[dict[str, Any]], service: str) -> int:
        count = 0
        for row in rows:
            if row.get("Service") != service:
                continue
            state = str(row.get("State", "")).lower()
            status = str(row.get("Status", "")).lower()
            if state == "running" or status.startswith("up"):
                count += 1
        return count

    async def _scale(self, params: dict[str, Any]) -> dict[str, Any]:
        project_dir = str(params["project_dir"])
        service = params["service"]
        replicas = int(params["replicas"])
        compose_file = self._compose_file(project_dir)
        if compose_file is None:
            raise FileNotFoundError(f"{project_dir} 下没有 compose 文件")

        before = self._running(await self._ps(project_dir, compose_file.name), service)
        await asyncio.to_thread(
            self._run,
            [
                *self._host_args(), "compose", "-f", compose_file.name, "up", "-d",
                "--no-deps", "--scale", f"{service}={replicas}", service,
            ],
            project_dir,
        )
        handle = json.dumps(
            {
                "project_dir": project_dir,
                "compose_file": compose_file.name,
                "service": service,
                "before": before,
                "target": replicas,
            }
        )
        return {"handle": handle, "before": before, "target": replicas}

    async def _undo_scale(self, params: dict[str, Any]) -> dict[str, Any]:
        state = json.loads(params["handle"])
        await asyncio.to_thread(
            self._run,
            [
                *self._host_args(), "compose", "-f", state["compose_file"], "up", "-d",
                "--no-deps", "--scale", f"{state['service']}={state['before']}", state["service"],
            ],
            state["project_dir"],
        )
        return {"restored": state["before"]}

    # -- 发布:把服务切到指定镜像 -------------------------------------
    #
    # 发布是"一次外部改变",不是平台自己造的一条发布流水线:下游仍是 compose,
    # 平台只负责登记这次切换、读出切换前的镜像、并保证切得回来。
    # 撤销是重新部署切换前那个镜像(对称操作),所以窗口是"项目还在就一直能撤"。

    async def _release(self, params: dict[str, Any]) -> dict[str, Any]:
        project_dir = str(params.get("project_dir") or "")
        service = str(params.get("service") or "")
        target_image = str(params.get("image") or "")
        missing = [
            name
            for name, value in (
                ("project_dir", project_dir),
                ("service", service),
                ("image", target_image),
            )
            if not value
        ]
        if missing:
            # 参数不全:什么都没碰过,记 failed(可重试),不是"不知道动没动"。
            raise EffectNotApplied(f"发布缺参数:{'、'.join(missing)}")

        compose_file = self._compose_file(project_dir)
        if compose_file is None:
            raise EffectNotApplied(f"{project_dir} 下没有 compose 文件,不发布")

        rows = await self._ps(project_dir, compose_file.name)
        before_image = self._image_of(rows, service)
        if not before_image:
            # 读不到当前镜像就撤不回来;没有撤销承诺的发布不进第一类路径。
            raise EffectNotApplied(
                f"读不到服务 {service} 当前运行的镜像,无法保证可撤销,不发布"
            )

        env = {self.image_env: target_image}
        try:
            await self._exec(
                [*self._host_args(), "compose", "-f", compose_file.name, "pull", service],
                project_dir,
                env,
            )
        except subprocess.CalledProcessError as exc:
            # pull 失败时容器还没被替换:这是确定没动,可以重试。
            raise EffectNotApplied(f"拉取镜像失败,服务未变动:{exc}") from exc

        await self._exec(
            [*self._host_args(), "compose", "-f", compose_file.name, "up", "-d",
             "--no-deps", service],
            project_dir,
            env,
        )

        handle = json.dumps(
            {
                "project_dir": project_dir,
                "compose_file": compose_file.name,
                "service": service,
                "image_env": self.image_env,
                "before_image": before_image,
                "target_image": target_image,
            }
        )
        return {"handle": handle, "before_image": before_image, "target_image": target_image}

    async def _undo_release(self, params: dict[str, Any]) -> dict[str, Any]:
        state = json.loads(params["handle"])
        await self._exec(
            [*self._host_args(), "compose", "-f", state["compose_file"], "up", "-d",
             "--no-deps", state["service"]],
            state["project_dir"],
            {state.get("image_env") or DEFAULT_IMAGE_ENV: state["before_image"]},
        )
        return {"restored": state["before_image"]}
