# engine/plugin_manager/registry.py
"""插件注册表——发现、实例化、索引与生命周期。

发现语义:
- builtin 目录默认 `cwd/plugins/builtin`,可被参数覆盖;
- `PLUGINS_EXTRA_DIRS`(冒号分隔)为外部插件根,每个根下的 `<pkg>/plugin.yaml`
  以包路径导入(根会加入 sys.path)——这是闭源插件的挂载点;
- 单个插件的清单解析/导入/实例化失败只跳过自身(日志 + metrics),不影响其他插件;
- 同名插件重复注册视为配置错误,抛出。
"""

import importlib
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.shared.metrics import metrics

from .base import PluginBase
from .manifest import Manifest

logger = logging.getLogger(__name__)

DEFAULT_BUILTIN_DIR = Path.cwd() / "plugins" / "builtin"


@dataclass
class _CapabilityProvider:
    name: str
    priority: int


class PluginRegistry:
    def __init__(self) -> None:
        self._manifests: dict[str, Manifest] = {}
        self._instances: dict[str, PluginBase] = {}
        self._dirs: dict[str, Path] = {}
        self._event_index: dict[str, list[str]] = {}
        self._capability_index: dict[str, list[_CapabilityProvider]] = {}
        self._hook_index: dict[str, list[tuple[int, str]]] = {}
        self._launched = False

    # ------------------------------------------------------------------
    # 发现与注册
    # ------------------------------------------------------------------

    def discover(
        self,
        builtin_dir: Path | None = None,
        extra_dirs: list[str] | None = None,
    ) -> int:
        """扫描并加载全部插件,返回成功加载数量。幂等:重复调用前先清空。"""
        if self._manifests:
            self._reset()

        roots: list[tuple[Path, str]] = []  # (搜索根, 模块前缀)
        base = Path(builtin_dir) if builtin_dir else DEFAULT_BUILTIN_DIR
        if base.is_dir():
            if base.resolve() == DEFAULT_BUILTIN_DIR.resolve():
                roots.append((base, "plugins.builtin"))
            else:
                # 自定义/测试根:根自身入 sys.path,包名取目录名
                if str(base) not in sys.path:
                    sys.path.insert(0, str(base))
                roots.append((base, ""))
        for extra in extra_dirs or self._extra_dirs_from_env():
            root = Path(extra)
            if root.is_dir():
                if str(root) not in sys.path:
                    sys.path.insert(0, str(root))
                roots.append((root, ""))  # 模块名 = <pkg>.plugin

        for root, prefix in roots:
            # builtin 为两级(<类别>/<插件>),外部根允许单级(<插件>)
            manifests = sorted(
                set(root.glob("*/plugin.yaml")) | set(root.glob("*/*/plugin.yaml"))
            )
            for manifest_path in manifests:
                try:
                    self._load_one(root, prefix, manifest_path)
                except Exception as e:
                    metrics.increment(
                        "plugin_discovery_errors_total",
                        {"path": str(manifest_path.parent.name)},
                    )
                    logger.error("Failed to load plugin at %s: %s", manifest_path, e)
        logger.info(
            "Plugin registry loaded %d plugin(s): %s",
            len(self._instances),
            ", ".join(sorted(self._instances)) or "<none>",
        )
        return len(self._instances)

    @staticmethod
    def _extra_dirs_from_env() -> list[str]:
        raw = os.environ.get("PLUGINS_EXTRA_DIRS", "")
        return [d for d in raw.split(":") if d]

    def _load_one(self, root: Path, prefix: str, manifest_path: Path) -> None:
        manifest = Manifest.from_yaml(manifest_path)
        rel = manifest_path.parent.relative_to(root)
        module_name = ".".join((([prefix] if prefix else []) + list(rel.parts) + ["plugin"]))
        module = importlib.import_module(module_name)
        instance = getattr(module, manifest.class_name)()
        self.register(manifest, instance, plugin_dir=manifest_path.parent)

    def plugin_dir(self, name: str) -> Path | None:
        """插件目录(含 plugin.yaml 的目录);未注册返回 None。"""
        return self._dirs.get(name)

    def register(
        self, manifest: Manifest, instance: PluginBase, plugin_dir: Path | None = None
    ) -> None:
        if manifest.name in self._manifests:
            raise ValueError(f"Duplicate plugin name: {manifest.name}")

        self._manifests[manifest.name] = manifest
        self._instances[manifest.name] = instance
        if plugin_dir is not None:
            self._dirs[manifest.name] = plugin_dir

        for event in manifest.event_subscriptions:
            self._event_index.setdefault(event, []).append(manifest.name)
        for capability in manifest.capabilities:
            provider = _CapabilityProvider(
                name=manifest.name,
                priority=manifest.capabilities_priority.get(capability, 0),
            )
            self._capability_index.setdefault(capability, []).append(provider)
            self._capability_index[capability].sort(
                key=lambda p: p.priority, reverse=True
            )
        for sub in manifest.hooks_subscribed:
            self._hook_index.setdefault(sub.point, []).append((sub.priority, manifest.name))
            self._hook_index[sub.point].sort(key=lambda item: item[0], reverse=True)

    def _reset(self) -> None:
        self._manifests.clear()
        self._instances.clear()
        self._dirs.clear()
        self._event_index.clear()
        self._capability_index.clear()
        self._hook_index.clear()
        self._launched = False

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get(self, name: str) -> PluginBase | None:
        return self._instances.get(name)

    def manifest(self, name: str) -> Manifest | None:
        return self._manifests.get(name)

    def names(self) -> list[str]:
        return sorted(self._instances)

    def instances_for_event(self, event: str) -> list[PluginBase]:
        return [
            self._instances[name] for name in self._event_index.get(event, [])
            if name in self._instances
        ]

    def hook_subscribers(self, point: str) -> list[tuple[Manifest, PluginBase, Any]]:
        """按优先级降序返回 (manifest, 实例, 订阅声明)。"""
        subs: list[tuple[int, str]] = self._hook_index.get(point, [])
        out: list[tuple[Manifest, PluginBase, Any]] = []
        for _, name in subs:
            manifest = self._manifests.get(name)
            instance = self._instances.get(name)
            if manifest is None or instance is None:
                continue
            declaration = next(
                s for s in manifest.hooks_subscribed if s.point == point
            )
            out.append((manifest, instance, declaration))
        return out

    def best_capability_provider(self, capability: str) -> PluginBase | None:
        providers = self._capability_index.get(capability, [])
        return self._instances.get(providers[0].name) if providers else None

    # ------------------------------------------------------------------
    # 生命周期与执行
    # ------------------------------------------------------------------

    async def launch(self) -> None:
        """逐插件 on_startup,单插件失败被隔离(日志 + metrics),不中断其他插件。"""
        for name, instance in self._instances.items():
            try:
                await instance.on_startup()
                logger.info("Plugin %s started", name)
            except Exception as e:
                metrics.increment(
                    "plugin_startup_errors_total", {"plugin": name}
                )
                logger.error("Plugin %s failed to start: %s", name, e)
        self._launched = True

    async def shutdown(self) -> None:
        for name, instance in self._instances.items():
            try:
                await instance.on_shutdown()
            except Exception as e:
                logger.error("Plugin %s failed to shut down: %s", name, e)
        self._launched = False

    async def health_check_all(self) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for name, instance in self._instances.items():
            try:
                results[name] = bool(await instance.health_check())
            except Exception:
                results[name] = False
        return results

    async def run_capability(self, capability: str, params: dict) -> dict:
        """由优先级最高的提供者执行能力;无提供者抛 LookupError。

        任务名来自 manifest 的 tasks 映射,缺省为能力名的下划线形式。
        """
        provider = self.best_capability_provider(capability)
        if provider is None:
            raise LookupError(f"No provider for capability: {capability}")
        manifest = next(
            m for m in self._manifests.values() if capability in m.capabilities
        )
        task = manifest.tasks.get(capability, capability.replace(".", "_"))
        return await provider.execute_task(task, params)


# 生产用单例(app lifespan 调 discover/launch;runtime 与总线引用它)
registry = PluginRegistry()
