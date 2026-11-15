# engine/plugin_manager/registry.py
"""插件注册表——发现、实例化、索引与生命周期。

发现语义:
- builtin 目录默认 `cwd/plugins/builtin`,可被参数覆盖;
- `PLUGINS_EXTRA_DIRS`(冒号分隔)为外部插件根,每个根下的 `<pkg>/plugin.yaml`
  以包路径导入(根会加入 sys.path)——这是进程内插件的挂载点;
- 单个插件的清单解析/导入/实例化失败只跳过自身(日志 + metrics),不影响其他插件;
- 同一清单可以注册多个实例(每租户/每目标一个),实例键默认取清单名。

能力解析:
- 不带 tenant/binding 时按全局优先级选(单租户与控制面形态);
- 带 tenant/binding 时按 (租户, 目标) 精确匹配,选不到直接抛,不跨目标回退。

启停语义:
- 发现 ≠ 启用。发现只把清单记进 `available()`,启用的才 import、注册、进索引;
- 启停可以在运行期做(`enable` / `disable` / `rescan`),不用重启进程:启用是
  "导入 + 注册 + on_startup",停用是"on_shutdown + 摘掉索引"。停用后这个插件
  既不在 `names()` 里,也解析不到它的能力;
- 决定从哪来:运行期显式决定(`set_decisions`,由控制台写入并持久化)> 
  `PLUGINS_ENABLED` 白名单 > `PLUGINS_DISABLED` > 清单 `default_enabled`。
  白名单里写了没人认领的名字时点名告警——写错一个字母不该长得像"这个部署确实
  一个插件都不装"。
"""

import importlib
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.shared.metrics import metrics

from .base import PluginBase
from .manifest import Manifest

logger = logging.getLogger(__name__)

DEFAULT_BUILTIN_DIR = Path.cwd() / "plugins" / "builtin"


def _env_names(var: str) -> set[str] | None:
    """逗号或冒号分隔的插件名清单;变量不存在返回 None。"""
    raw = os.environ.get(var)
    if raw is None:
        return None
    return {item.strip() for item in raw.replace(":", ",").split(",") if item.strip()}


def plugin_enabled(name: str, default_enabled: bool = True) -> bool:
    """发现 != 启用。

    PLUGINS_ENABLED 给了就只加载清单里的(白名单);
    否则按 PLUGINS_DISABLED 排除,再退回清单里的 default_enabled。
    """
    enabled = _env_names("PLUGINS_ENABLED")
    if enabled is not None:
        return name in enabled
    disabled = _env_names("PLUGINS_DISABLED") or set()
    if name in disabled:
        return False
    return default_enabled


@dataclass
class _CapabilityProvider:
    key: str
    priority: int


@dataclass
class Discovered:
    """发现阶段记下的一件事:清单 + 它在哪 + 怎么导入。

    导入推迟到真要启用时:清单能读出来就说明控制台能把它讲清楚,而坏掉的实现
    不该在"只是看一眼插件列表"时把引擎拖下水。
    """

    manifest: Manifest
    plugin_dir: Path
    module_name: str


@dataclass
class PluginState:
    """一个清单此刻的状态:声明、启用与否、在哪些实例键上活着、为什么是这个状态。"""

    manifest: Manifest
    enabled: bool
    instances: list[str] = field(default_factory=list)
    reason: str = ""


class PluginRegistry:
    def __init__(self) -> None:
        self._manifests: dict[str, Manifest] = {}
        self._instances: dict[str, PluginBase] = {}
        self._instance_names: dict[str, str] = {}  # 实例键 -> 清单名
        self._dirs: dict[str, Path] = {}
        self._event_index: dict[str, list[str]] = {}
        self._capability_index: dict[str, list[_CapabilityProvider]] = {}
        self._effect_index: dict[str, list[_CapabilityProvider]] = {}
        self._hook_index: dict[str, list[tuple[int, str, Any]]] = {}
        self._available: dict[str, Discovered] = {}
        # 运行期显式决定(清单名 -> 启停);由控制台写入,启动时从库里装回来
        self._decisions: dict[str, bool] = {}
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
        if self._available or self._manifests:
            self._reset()

        for manifest_path, module_name in self._scan(builtin_dir, extra_dirs):
            try:
                self._record(manifest_path, module_name)
            except Exception as e:
                metrics.increment(
                    "plugin_discovery_errors_total",
                    {"path": str(manifest_path.parent.name)},
                )
                logger.error("Failed to load plugin at %s: %s", manifest_path, e)

        for name in sorted(self._available):
            if self._enabled(self._available[name].manifest):
                self._activate_quietly(name)

        self._warn_unmatched_whitelist()
        count = len(self._instances)
        log = logger.info if count else logger.warning
        log(
            "Plugin registry loaded %d of %d discovered plugin(s): %s",
            count,
            len(self._available),
            ", ".join(sorted(self._instances)) or "<none>",
        )
        return count

    def rescan(self, extra_dirs: list[str] | None = None) -> dict[str, list[str]]:
        """重新扫一遍目录,不重启进程。

        只处理两件事:**新出现的**清单按决定启用,**已经不在磁盘上的**停掉。
        已加载且清单没变的实例原样留着——一次点"重新扫描"不该把所有插件的连接
        都断一遍。返回 {"added": [...], "removed": [...], "changed": [...]}。
        """
        added: list[str] = []
        removed: list[str] = []
        changed: list[str] = []
        seen: dict[str, Discovered] = {}

        for manifest_path, module_name in self._scan(None, extra_dirs):
            try:
                manifest = Manifest.from_yaml(manifest_path)
            except Exception as e:
                metrics.increment(
                    "plugin_discovery_errors_total",
                    {"path": str(manifest_path.parent.name)},
                )
                logger.error("Failed to load plugin at %s: %s", manifest_path, e)
                continue
            if manifest.name in seen:
                logger.error(
                    "Plugin %s 出现两次(%s 与 %s),只认第一个",
                    manifest.name,
                    seen[manifest.name].plugin_dir,
                    manifest_path.parent,
                )
                continue
            seen[manifest.name] = Discovered(manifest, manifest_path.parent, module_name)

        for name, found in sorted(seen.items()):
            known = self._available.get(name)
            if known is None:
                self._available[name] = found
                added.append(name)
                if self._enabled(found.manifest):
                    self._activate_quietly(name)
            elif known.manifest != found.manifest or known.plugin_dir != found.plugin_dir:
                # 清单在磁盘上变了:已在跑的实例保持不动,重启或显式 disable/enable 才换实现
                self._available[name] = found
                changed.append(name)

        for name in sorted(set(self._available) - set(seen)):
            self._available.pop(name, None)
            self._disable_now(name)
            removed.append(name)

        if added or removed or changed:
            logger.info(
                "Plugin rescan: added=%s removed=%s changed=%s", added, removed, changed
            )
        return {"added": added, "removed": removed, "changed": changed}

    @staticmethod
    def _scan(
        builtin_dir: Path | None, extra_dirs: list[str] | None
    ) -> list[tuple[Path, str]]:
        """把搜索根展开成 (清单路径, 模块名)。只读磁盘,不 import。"""
        roots: list[tuple[Path, str]] = []  # (搜索根, 模块前缀)
        base = Path(builtin_dir) if builtin_dir else DEFAULT_BUILTIN_DIR
        if base.is_dir():
            if builtin_dir is None or base.resolve() == DEFAULT_BUILTIN_DIR.resolve():
                roots.append((base, "plugins.builtin"))
            else:
                # 自定义/测试根:根自身入 sys.path,包名取目录名
                if str(base) not in sys.path:
                    sys.path.insert(0, str(base))
                roots.append((base, ""))
        for extra in extra_dirs if extra_dirs is not None else PluginRegistry._extra_dirs_from_env():
            root = Path(extra)
            if root.is_dir():
                if str(root) not in sys.path:
                    sys.path.insert(0, str(root))
                roots.append((root, ""))  # 模块名 = <pkg>.plugin

        out: list[tuple[Path, str]] = []
        for root, prefix in roots:
            # builtin 为两级(<类别>/<插件>),外部根允许单级(<插件>)
            manifests = sorted(
                set(root.glob("*/plugin.yaml")) | set(root.glob("*/*/plugin.yaml"))
            )
            for manifest_path in manifests:
                rel = manifest_path.parent.relative_to(root)
                module_name = ".".join(
                    (([prefix] if prefix else []) + list(rel.parts) + ["plugin"])
                )
                out.append((manifest_path, module_name))
        return out

    @staticmethod
    def _extra_dirs_from_env() -> list[str]:
        raw = os.environ.get("PLUGINS_EXTRA_DIRS", "")
        return [d for d in raw.split(":") if d]

    def _record(self, manifest_path: Path, module_name: str) -> None:
        """读清单并登记为"发现到"。同名清单只认第一个,重复是配置错误。"""
        manifest = Manifest.from_yaml(manifest_path)
        existing = self._available.get(manifest.name)
        if existing is not None:
            raise ValueError(
                f"插件名 {manifest.name} 出现两次:{existing.plugin_dir} 与 "
                f"{manifest_path.parent}。插件名是唯一标识,换一个目录名或改名"
            )
        self._available[manifest.name] = Discovered(manifest, manifest_path.parent, module_name)

    def _enabled(self, manifest: Manifest) -> bool:
        """运行期决定 > 白名单/黑名单 > 清单默认。"""
        if manifest.name in self._decisions:
            return self._decisions[manifest.name]
        return plugin_enabled(manifest.name, manifest.default_enabled)

    def _decision_reason(self, manifest: Manifest) -> str:
        if manifest.name in self._decisions:
            return "运行期启停" if self._decisions[manifest.name] else "运行期停用"
        if _env_names("PLUGINS_ENABLED") is not None:
            return "在 PLUGINS_ENABLED 白名单里"
        if manifest.name in (_env_names("PLUGINS_DISABLED") or set()):
            return "在 PLUGINS_DISABLED 里"
        return "清单默认启用" if manifest.default_enabled else "清单声明 default_enabled: false"

    def _warn_unmatched_whitelist(self) -> None:
        """白名单写了没人认领的名字:这是配置事故,不能和"确实没装插件"长得一样。"""
        wanted = _env_names("PLUGINS_ENABLED")
        if not wanted:
            return
        unknown = sorted(wanted - set(self._available))
        if unknown:
            logger.warning(
                "PLUGINS_ENABLED 里有 %d 个名字没人认领:%s;已发现的插件是:%s",
                len(unknown),
                ", ".join(unknown),
                ", ".join(sorted(self._available)) or "<none>",
            )

    def _activate_quietly(self, name: str) -> None:
        """发现期的启用:失败只跳过自身(日志 + metrics),不影响其他插件。"""
        try:
            self._activate(self._available[name])
        except Exception as e:
            metrics.increment("plugin_discovery_errors_total", {"path": name})
            logger.error("Failed to activate plugin %s: %s", name, e)

    def _activate(self, found: Discovered) -> None:
        """实例化 + 注册。原子性由 register 保证:注册不成功就什么都不留。

        进程外插件(清单写了 `endpoint`)不导入任何代码,实例换成一个远程代理——
        声明与进程内的那份完全一样,所以这里只有一个分支,不在调用方分两套。
        """
        if found.manifest.endpoint:
            from .grpc_loader import make_proxy

            instance = make_proxy(found.manifest, found.manifest.endpoint)
            self.register(found.manifest, instance, plugin_dir=found.plugin_dir)
            return
        module = importlib.import_module(found.module_name)
        instance = getattr(module, found.manifest.class_name)()
        self.register(found.manifest, instance, plugin_dir=found.plugin_dir)

    def plugin_dir(self, name: str) -> Path | None:
        """插件目录(含 plugin.yaml 的目录)。名字可以是实例键,也可以是清单名。"""
        if name in self._dirs:
            return self._dirs[name]
        if name in self._available:
            return self._available[name].plugin_dir
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

        **全部校验在任何写入之前完成**:一个注册失败的插件不该在索引里留下半分
        痕迹——否则日志说"加载失败",它却还能被解析到,这种状态没人能查。
        """
        instance_key = key or manifest.name
        existing = self._manifests.get(manifest.name)
        if existing is not None and existing != manifest:
            raise ValueError(f"Duplicate plugin name with different manifest: {manifest.name}")
        if instance_key in self._instances:
            raise ValueError(f"Duplicate plugin instance key: {instance_key}")
        for capability in manifest.effects:
            if capability not in manifest.capabilities:
                raise ValueError(
                    f"{manifest.name}: effect {capability} 未列入 capabilities,解析不到提供者"
                )

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
            provider = _CapabilityProvider(
                key=instance_key,
                priority=manifest.capabilities_priority.get(capability, 0),
            )
            self._effect_index.setdefault(capability, []).append(provider)
            self._effect_index[capability].sort(key=lambda p: (p.priority, p.key), reverse=True)

        for sub in manifest.hooks_subscribed:
            # 订阅声明跟着索引一起存:同一个插件对同一扩展点写两条订阅(observe + veto)
            # 时,反查第一条会把两条都变成第一条的 mode——链上执行的行为就错了。
            self._hook_index.setdefault(sub.point, []).append(
                (sub.priority, instance_key, sub)
            )
            self._hook_index[sub.point].sort(key=lambda item: item[0], reverse=True)

    def _drop_instance(self, key: str) -> None:
        """把一个实例从所有索引里摘掉。停用不是"打个标记",是它真的不再被解析到。"""
        self._instances.pop(key, None)
        self._instance_names.pop(key, None)
        self._dirs.pop(key, None)
        for index in (self._event_index,):
            for event, keys in list(index.items()):
                index[event] = [k for k in keys if k != key]
                if not index[event]:
                    index.pop(event, None)
        for index in (self._capability_index, self._effect_index):
            for capability, providers in list(index.items()):
                index[capability] = [p for p in providers if p.key != key]
                if not index[capability]:
                    index.pop(capability, None)
        for point, subs in list(self._hook_index.items()):
            self._hook_index[point] = [s for s in subs if s[1] != key]
            if not self._hook_index[point]:
                self._hook_index.pop(point, None)

    def _reset(self) -> None:
        self._manifests.clear()
        self._instances.clear()
        self._instance_names.clear()
        self._dirs.clear()
        self._event_index.clear()
        self._capability_index.clear()
        self._effect_index.clear()
        self._hook_index.clear()
        self._available.clear()
        self._launched = False

    # ------------------------------------------------------------------
    # 运行期启停
    # ------------------------------------------------------------------

    def set_decisions(self, decisions: dict[str, bool]) -> None:
        """装回持久化的启停决定(启动时由 lifespan 调用)。只记,不加载。"""
        self._decisions = {str(k): bool(v) for k, v in decisions.items()}

    def decisions(self) -> dict[str, bool]:
        return dict(self._decisions)

    def states(self) -> list[PluginState]:
        """每个被发现清单的当前状态——控制台据此画"已启用/未启用"。

        发现 ≠ 启用这件事只有在这个列表里才看得见:只列 `names()` 的话,
        未启用的插件在页面上根本不存在,人就没法把它打开。
        """
        out: list[PluginState] = []
        # 发现到的:启没启用都列出来,否则页面上没有地方把它打开
        for name in sorted(self._available):
            manifest = self._available[name].manifest
            instances = sorted(
                key for key, owner in self._instance_names.items() if owner == name
            )
            out.append(
                PluginState(
                    manifest=manifest,
                    enabled=bool(instances),
                    instances=instances,
                    reason=self._decision_reason(manifest),
                )
            )
        # 直接 register() 进来的(进程外代理、单测手工挂的):没有目录,不能启停,
        # 但它们确实在流程里——不列出来等于把活着的东西藏起来
        for name in sorted(set(self._manifests) - set(self._available)):
            instances = sorted(
                key for key, owner in self._instance_names.items() if owner == name
            )
            out.append(
                PluginState(
                    manifest=self._manifests[name],
                    enabled=bool(instances),
                    instances=instances,
                    reason="直接注册(不在插件目录里)",
                )
            )
        return out

    def available(self) -> list[Manifest]:
        """发现到的清单,不管启没启用。"""
        return [self._available[name].manifest for name in sorted(self._available)]

    def is_loaded(self) -> bool:
        """注册表跑过发现没有。

        这个回答决定了"取不到插件"该怎么理解:注册表没跑过(单测直接调、引擎还没起)
        是"还没查",而跑过之后取不到是"这个部署确实没启用它"。两件事混在一起,
        开关就会变成装饰——关掉的插件靠一条直连兜底照常干活。
        """
        return bool(self._available) or bool(self._manifests)

    async def enable(self, name: str) -> None:
        """启用一个已发现的插件:导入、注册、启动。已经在跑就什么都不做。"""
        found = self._available.get(name)
        if found is None:
            raise LookupError(f"没有发现这个插件:{name}")
        self._decisions[name] = True
        if name in self._manifests:
            return
        self._activate(found)
        if self._launched:
            for key, instance in self._instances.items():
                if self._instance_names.get(key) != name:
                    continue
                try:
                    await instance.on_startup()
                    logger.info("Plugin %s started (runtime enable)", key)
                except Exception as e:
                    metrics.increment("plugin_startup_errors_total", {"plugin": key})
                    logger.error("Plugin %s failed to start: %s", key, e)

    async def disable(self, name: str) -> None:
        """停用一个插件:关掉它的实例,再从索引里摘掉。已经停了也不报错。"""
        if name not in self._available:
            raise LookupError(f"没有发现这个插件:{name}")
        self._decisions[name] = False
        await self._disable_now_async(name)

    def _disable_now(self, name: str) -> None:
        """同步摘除(磁盘上已经不在了的那种),不留 on_shutdown 的机会。"""
        keys = [k for k, owner in self._instance_names.items() if owner == name]
        for key in keys:
            self._drop_instance(key)
        self._manifests.pop(name, None)

    async def _disable_now_async(self, name: str) -> None:
        keys = [k for k, owner in self._instance_names.items() if owner == name]
        for key in keys:
            instance = self._instances.get(key)
            if instance is not None:
                try:
                    await instance.on_shutdown()
                except Exception as e:
                    logger.error("Plugin %s failed to shut down: %s", key, e)
            self._drop_instance(key)
        self._manifests.pop(name, None)

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
        """按清单名取清单;**也接受实例键**,这两种名字在调用方眼里常被混用。"""
        if name in self._manifests:
            return self._manifests[name]
        owner = self._instance_names.get(name)
        return self._manifests.get(owner) if owner else None

    def names(self) -> list[str]:
        """活着的**实例键**。同一清单挂多个实例时,这里会出现多个键。"""
        return sorted(self._instances)

    def manifests(self) -> list[Manifest]:
        """已注册的清单,每个清单一次——实例可能有很多个,声明只有一份。"""
        return [self._manifests[name] for name in sorted(self._manifests)]

    def webhook_adapter(self, source: str) -> PluginBase | None:
        """哪个实例负责这个来源的 Webhook。

        来源名由适配器自己声明(`source = "github" | "gitlab" | "cnb"`),核心
        不认识任何一家的语法;同一个来源只该有一个提供者。
        """
        found: list[PluginBase] = []
        for key, instance in self._instances.items():
            if getattr(instance, "source", "") != source:
                continue
            manifest = self._manifests.get(self._instance_names.get(key, ""))
            if manifest is not None and "webhook.receive" not in manifest.capabilities:
                continue
            found.append(instance)
        if len(found) > 1:
            raise LookupError(f"来源 {source!r} 有多个 webhook 适配器,拒绝猜一个")
        return found[0] if found else None

    def instances_for_event(self, event: str) -> list[PluginBase]:
        return [
            self._instances[key] for key in self._event_index.get(event, [])
            if key in self._instances
        ]

    def hook_subscribers(self, point: str) -> list[tuple[Manifest, PluginBase, Any]]:
        """按优先级降序返回 (manifest, 实例, 订阅声明)。"""
        subs: list[tuple[int, str, Any]] = self._hook_index.get(point, [])
        out: list[tuple[Manifest, PluginBase, Any]] = []
        for _, key, declaration in subs:
            manifest_name = self._instance_names.get(key, "")
            manifest = self._manifests.get(manifest_name)
            instance = self._instances.get(key)
            if manifest is None or instance is None:
                continue
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

    def declared_effects(self) -> dict[str, dict[str, Any]]:
        """这个部署里声明了效果的能力 → 标签与参数名。

        给 intent 提供者当菜单:点一个这里没有的能力,平台只会把它记成阻断。
        不管插件绑在哪个目标上,"有人声明过"都是部署级的事实。
        """
        out: dict[str, dict[str, Any]] = {}
        for capability, providers in self._effect_index.items():
            for provider in providers:
                manifest = self._manifests.get(self._instance_names.get(provider.key, ""))
                decl = manifest.effects.get(capability) if manifest else None
                if decl is None:
                    continue
                out[capability] = {"label": decl.label, "args": list(decl.execute_args)}
                break
        return out

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
