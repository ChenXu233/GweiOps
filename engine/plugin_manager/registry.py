# engine/plugin_manager/registry.py
"""插件注册表——发现、实例化、索引与生命周期。

发现语义:
- builtin 目录默认 `cwd/plugins/builtin`,可被参数覆盖;
- `PLUGINS_EXTRA_DIRS`(冒号分隔)为外部插件根,每个根下的 `<pkg>/plugin.yaml`
  以包路径导入(根会加入 sys.path)——这是闭源插件的挂载点;
- 单个插件的清单解析/导入/实例化失败只跳过自身(日志 + metrics),不影响其他插件;
- 同一清单可以注册多个实例(每租户/每目标一个),实例键默认取清单名。

能力解析:
- 不带 tenant/binding 时按全局优先级选(单租户与控制面形态);
- 带 tenant/binding 时按 (租户, 目标) 精确匹配,选不到直接抛,不跨目标回退。
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
    key: str
    priority: int


class PluginRegistry:
    def __init__(self) -> None:
        self._manifests: dict[str, Manifest] = {}
        self._instances: dict[str, PluginBase] = {}
        self._instance_names: dict[str, str] = {}  # 实例键 -> 清单名
        self._dirs: dict[str, Path] = {}
        self._event_index: dict[str, list[str]] = {}
        self._capability_index: dict[str, list[_CapabilityProvider]] = {}
        self._effect_index: dict[str, list[_CapabilityProvider]] = {}
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
            "Plugin registry loaded %d plugin instance(s): %s",
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
        if name in self._dirs:
            return self._dirs[name]
        keys = [k for k, n in self._instance_names.items() if n == name]
        return self._dirs.get(keys[0]) if len(keys) == 1 else None

    def register(
        self,
        manifest: Manifest,
        instance: PluginBase,
        plugin_dir: Path | None = None,
        key: str | None = None,
    ) -> None:
        """注册一个实例。

        key 默认取清单名;同一清单要挂多个实例时(每租户/每目标一个)显式给 key。
        同名清单内容必须一致,否则视为配置错误。
        """
        instance_key = key or manifest.name
        existing = self._manifests.get(manifest.name)
        if existing is not None and existing != manifest:
            raise ValueError(f"Duplicate plugin name with different manifest: {manifest.name}")
        if instance_key in self._instances:
            raise ValueError(f"Duplicate plugin instance key: {instance_key}")

        self._manifests.setdefault(manifest.name, manifest)
        self._instances[instance_key] = instance
        self._instance_names[instance_key] = manifest.name
        if plugin_dir is not None:
            self._dirs[instance_key] = plugin_dir

        for event in manifest.event_subscriptions:
            self._event_index.setdefault(event, []).append(instance_key)
        for capability in manifest.capabilities:
            provider = _CapabilityProvider(
                key=instance_key,
                priority=manifest.capabilities_priority.get(capability, 0),
            )
            self._capability_index.setdefault(capability, []).append(provider)
            self._capability_index[capability].sort(
                key=lambda p: p.priority, reverse=True
            )
        for capability in manifest.effects:
            if capability not in manifest.capabilities:
                raise ValueError(
                    f"{manifest.name}: effect {capability} 未列入 capabilities,解析不到提供者"
                )
            provider = _CapabilityProvider(
                key=instance_key,
                priority=manifest.capabilities_priority.get(capability, 0),
            )
            self._effect_index.setdefault(capability, []).append(provider)
            self._effect_index[capability].sort(key=lambda p: (p.priority, p.key), reverse=True)

        for sub in manifest.hooks_subscribed:
            self._hook_index.setdefault(sub.point, []).append((sub.priority, instance_key))
            self._hook_index[sub.point].sort(key=lambda item: item[0], reverse=True)

    def _reset(self) -> None:
        self._manifests.clear()
        self._instances.clear()
        self._instance_names.clear()
        self._dirs.clear()
        self._event_index.clear()
        self._capability_index.clear()
        self._effect_index.clear()
        self._hook_index.clear()
        self._launched = False

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get(self, key: str) -> PluginBase | None:
        """按实例键查询;键不存在时,若清单名唯一对应一个实例也返回它。"""
        if key in self._instances:
            return self._instances[key]
        keys = [k for k, n in self._instance_names.items() if n == key]
        return self._instances[keys[0]] if len(keys) == 1 else None

    def manifest(self, name: str) -> Manifest | None:
        return self._manifests.get(name)

    def names(self) -> list[str]:
        return sorted(self._instances)

    def instances_for_event(self, event: str) -> list[PluginBase]:
        return [
            self._instances[key] for key in self._event_index.get(event, [])
            if key in self._instances
        ]

    def hook_subscribers(self, point: str) -> list[tuple[Manifest, PluginBase, Any]]:
        """按优先级降序返回 (manifest, 实例, 订阅声明)。"""
        subs: list[tuple[int, str]] = self._hook_index.get(point, [])
        out: list[tuple[Manifest, PluginBase, Any]] = []
        for _, key in subs:
            manifest_name = self._instance_names.get(key, "")
            manifest = self._manifests.get(manifest_name)
            instance = self._instances.get(key)
            if manifest is None or instance is None:
                continue
            declaration = next(
                s for s in manifest.hooks_subscribed if s.point == point
            )
            out.append((manifest, instance, declaration))
        return out

    def best_capability_provider(self, capability: str) -> PluginBase | None:
        providers = self._capability_index.get(capability, [])
        return self._instances.get(providers[0].key) if providers else None

    def capability_bindings(self, capability: str) -> list[tuple[str, str, str, int]]:
        """(实例键, tenant, binding, priority) —— 用于诊断"为什么没选到它"。"""
        out: list[tuple[str, str, str, int]] = []
        for provider in self._capability_index.get(capability, []):
            instance = self._instances.get(provider.key)
            out.append(
                (
                    provider.key,
                    getattr(instance, "tenant", ""),
                    getattr(instance, "binding", ""),
                    provider.priority,
                )
            )
        return out

    def resolve(self, capability: str, *, tenant: str = "", binding: str = "") -> PluginBase:
        """按 (租户, 目标) 精确选择提供者。

        不做模糊匹配、不跨目标回退:同一能力在 A 目标的提供者绝不服务 B 目标。
        控制面能力(不针对具体环境的)用 tenant="" binding="" 解析。
        """
        providers = self._capability_index.get(capability, [])
        if not providers:
            raise LookupError(f"No provider for capability: {capability}")
        return self._choose(
            self._matching(providers, tenant, binding),
            capability,
            tenant,
            binding,
            available=self.capability_bindings(capability),
        )

    def _matching(
        self, providers: list[_CapabilityProvider], tenant: str, binding: str
    ) -> list[tuple[PluginBase, int]]:
        """按 (租户, 目标) 过滤,保持优先级顺序;租户精确优先于共享。"""
        exact: list[tuple[PluginBase, int]] = []
        shared: list[tuple[PluginBase, int]] = []
        for provider in providers:
            instance = self._instances.get(provider.key)
            if instance is None:
                continue
            if getattr(instance, "binding", "") != binding:
                continue
            instance_tenant = getattr(instance, "tenant", "")
            if instance_tenant == tenant:
                exact.append((instance, provider.priority))
            elif instance_tenant == "":
                shared.append((instance, provider.priority))
        return exact or shared

    @staticmethod
    def _choose(
        matches: list[tuple[PluginBase, int]],
        capability: str,
        tenant: str,
        binding: str,
        available: list | None = None,
    ) -> PluginBase:
        if not matches:
            raise LookupError(
                f"No provider for capability={capability} tenant={tenant!r} binding={binding!r}; "
                f"available={available if available is not None else 'n/a'}"
            )
        if len(matches) > 1 and matches[0][1] == matches[1][1]:
            names = ", ".join(sorted(type(i).__name__ for i, _ in matches if _ == matches[0][1]))
            raise LookupError(
                f"能力 {capability} 在 tenant={tenant!r} binding={binding!r} 上有并列提供者 "
                f"({names});请在清单里设置 capabilities_priority 明确默认"
            )
        return matches[0][0]

    def effect_decl(self, capability: str, *, tenant: str = "", binding: str = ""):
        """返回 (提供者, 效果声明)。只看真的声明了这个效果的插件。"""
        providers = self._effect_index.get(capability, [])
        if not providers:
            raise LookupError(f"No provider declares effect: {capability}")
        provider = self._choose(
            self._matching(providers, tenant, binding), capability, tenant, binding
        )
        key = self._key_of(provider) or ""
        manifest = self._manifests.get(self._instance_names.get(key, ""))
        decl = manifest.effects.get(capability) if manifest else None
        if decl is None:
            raise LookupError(f"{key} 没有声明 effect {capability}")
        return provider, decl

    def _key_of(self, instance: PluginBase) -> str | None:
        for key, candidate in self._instances.items():
            if candidate is instance:
                return key
        return None

    # ------------------------------------------------------------------
    # 生命周期与执行
    # ------------------------------------------------------------------

    async def launch(self) -> None:
        """逐插件 on_startup,单插件失败被隔离(日志 + metrics),不中断其他插件。"""
        for key, instance in self._instances.items():
            try:
                await instance.on_startup()
                logger.info("Plugin %s started", key)
            except Exception as e:
                metrics.increment("plugin_startup_errors_total", {"plugin": key})
                logger.error("Plugin %s failed to start: %s", key, e)
        self._launched = True

    async def shutdown(self) -> None:
        for key, instance in self._instances.items():
            try:
                await instance.on_shutdown()
            except Exception as e:
                logger.error("Plugin %s failed to shut down: %s", key, e)
        self._launched = False

    async def health_check_all(self) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for key, instance in self._instances.items():
            try:
                results[key] = bool(await instance.health_check())
            except Exception:
                results[key] = False
        return results

    async def run_capability(
        self,
        capability: str,
        params: dict,
        *,
        tenant: str | None = None,
        binding: str | None = None,
    ) -> dict:
        """执行一次能力调用。

        不给 tenant/binding 时按全局优先级选(单租户与控制面形态);给了就按
        (租户, 目标) 精确解析,选不到直接抛,不回退到别的目标。

        任务名来自**被选中提供者**的清单,不是任意一个声明了同名能力的清单。
        """
        if tenant is None and binding is None:
            provider = self.best_capability_provider(capability)
            if provider is None:
                raise LookupError(f"No provider for capability: {capability}")
        else:
            provider = self.resolve(capability, tenant=tenant or "", binding=binding or "")

        key = self._key_of(provider)
        manifest = self._manifests.get(self._instance_names.get(key or "", ""))
        task = (
            manifest.tasks.get(capability, capability.replace(".", "_"))
            if manifest
            else capability.replace(".", "_")
        )
        return await provider.execute_task(task, params)


# 生产用单例(app lifespan 调 discover/launch;runtime 与总线引用它)
registry = PluginRegistry()
