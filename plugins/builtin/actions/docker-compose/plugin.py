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
import subprocess
from pathlib import Path
from typing import Any, Callable

from engine.change_unit import Effect, Window
from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType

COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
LOCAL_BINDING = "local"

Runner = Callable[[list[str], str], str]


def run_compose(args: list[str], cwd: str) -> str:
    """真实调用 docker compose。只有它碰外部世界。"""
    proc = subprocess.run(
        ["docker", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return proc.stdout


class DockerComposeAction(PluginBase):
    def __init__(
        self,
        runner: Runner | None = None,
        binding: str = LOCAL_BINDING,
        tenant: str = "",
    ) -> None:
        self._dir = Path(__file__).parent
        self._run = runner or run_compose
        self.binding = binding
        self.tenant = tenant

    # -- 清单元数据 -------------------------------------------------

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="docker-compose",
            version="0.1.0",
            type=PluginType.ACTION,
            description="用 docker compose 执行可撤销的服务变更",
            capabilities=["compose.scale"],
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
