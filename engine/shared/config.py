# engine/shared/config.py
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from dotenv import dotenv_values
from pydantic import ValidationError
from pydantic_settings import BaseSettings


EXPOSE_MODES = ("never", "masked", "always")
READ_SCOPES = ("read", "operate")


@dataclass(frozen=True)
class FieldSpec:
    """一个配置项对外的规则:要不要回显、回显成什么、谁能看。

    默认 `never`:没声明过的东西不出去。想要回显就明写,别指望调用方猜。
    """

    name: str
    required: bool = False
    expose: str = "never"  # never | masked | always
    read_scope: str = "read"  # read | operate

    def __post_init__(self) -> None:
        if self.expose not in EXPOSE_MODES:
            raise ValueError(f"非法 expose: {self.expose!r}")
        if self.read_scope not in READ_SCOPES:
            raise ValueError(f"非法 read_scope: {self.read_scope!r}")


def mask_value(value: str) -> str:
    """掩码不是把值变短,是让人认得出"是不是这一把"。"""
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}…{value[-4:]}"


@dataclass
class ScopeDefinition:
    """定义一个配置 scope，用于按功能域分发配置。"""

    name: str
    prefix: str = ""
    description: str = ""
    required_keys: list[str] = field(default_factory=list)
    optional_keys: list[str] = field(default_factory=list)
    validator: Optional[Callable[["Settings"], bool]] = None
    fields: dict[str, FieldSpec] = field(default_factory=dict)
    # 给了模型就在写入时做形状校验:存进去之前拦住,而不是等运行期炸
    model: Optional[type] = None


class ConfigManager:
    """全局配置管理器，支持注册 scope 并按 scope 分发配置。"""

    def __init__(self) -> None:
        self._scopes: dict[str, ScopeDefinition] = {}
        self._settings: Optional[Settings] = None
        # 存进业务库的那一份。启动时加载一次,写入时原地更新,所以取值仍然是同步的。
        self._stored: dict[str, dict[str, str]] = {}

    # ------------------------------------------------------------------
    # Scope 注册
    # ------------------------------------------------------------------

    def register_scope(
        self,
        name: str,
        prefix: str,
        required: list[str] | None = None,
        optional: list[str] | None = None,
        *,
        expose: dict[str, str] | None = None,
        read_scope: dict[str, str] | None = None,
    ) -> None:
        """注册一个配置 scope。重复注册同名 scope 会被覆盖。

        Args:
            name:     scope 名称，例如 ``"github"``
            prefix:   环境变量前缀，例如 ``"GITHUB_APP_"``
            required: 必需的配置项字段名列表（不含前缀），例如 ``["app_id", "private_key"]``
            optional: 可选的配置项字段名列表（不含前缀）
        """
        expose = expose or {}
        read_scope = read_scope or {}
        specs: dict[str, FieldSpec] = {}
        for key in required or []:
            specs[key] = FieldSpec(
                key, required=True, expose=expose.get(key, "never"),
                read_scope=read_scope.get(key, "read"),
            )
        for key in optional or []:
            specs[key] = FieldSpec(
                key, required=False, expose=expose.get(key, "never"),
                read_scope=read_scope.get(key, "read"),
            )

        self._scopes[name] = ScopeDefinition(
            name=name,
            prefix=prefix,
            required_keys=required or [],
            optional_keys=optional or [],
            fields=specs,
        )

    def register_model_scope(
        self, name: str, model: type, prefix: str = ""
    ) -> None:
        """用 pydantic 模型声明配置:字段、必填、回显规则全写在模型里。

        ```
        class BotSettings(BaseModel):
            api_key: str = Field(..., json_schema_extra={"expose": "masked"})
            base_url: str = Field("", json_schema_extra={"expose": "always"})
        ```

        写入时会用它验证:形状不对当场拒绝,不会存进去等运行期才炸。
        """
        specs: dict[str, FieldSpec] = {}
        required: list[str] = []
        optional: list[str] = []
        for field_name, info in model.model_fields.items():
            extra = info.json_schema_extra or {}
            if not isinstance(extra, dict):
                extra = {}
            specs[field_name] = FieldSpec(
                field_name,
                required=info.is_required(),
                expose=extra.get("expose", "never"),
                read_scope=extra.get("read_scope", "read"),
            )
            (required if info.is_required() else optional).append(field_name)

        self._scopes[name] = ScopeDefinition(
            name=name,
            prefix=prefix,
            required_keys=required,
            optional_keys=optional,
            fields=specs,
            model=model,
        )

    def field_specs(self, scope_name: str) -> list[FieldSpec]:
        """这个 scope 对外要交代的全部字段:声明过的 + 库里多出来的。"""
        scope = self._scopes.get(scope_name)
        if scope is None:
            raise KeyError(f"Unknown scope: {scope_name!r}")
        specs = dict(scope.fields)
        for key in self._stored.get(scope_name, {}):
            specs.setdefault(key, FieldSpec(key))
        return list(specs.values())

    def validate_values(self, scope_name: str, values: dict[str, str]) -> None:
        """写入前校验。没给模型就不校验形状——那是声明方的选择。

        "还没填全"不算错误:缺什么由 validate_scope 单独报,不该拦住先填一半。
        拦的只是形状——类型不对、值不合法这类存进去会炸的东西。
        """
        scope = self._scopes.get(scope_name)
        if scope is None or scope.model is None:
            return
        merged = {**self.get_scope_config(scope_name), **values}
        try:
            scope.model(**merged)
        except ValidationError as exc:
            shape_errors = [e for e in exc.errors() if e.get("type") != "missing"]
            if shape_errors:
                raise

    def get_scope(self, name: str) -> Optional[ScopeDefinition]:
        """按名称获取已注册的 scope。"""
        return self._scopes.get(name)

    def list_scopes(self) -> list[ScopeDefinition]:
        """列出所有已注册的 scope。"""
        return list(self._scopes.values())

    # ------------------------------------------------------------------
    # Settings 懒加载
    # ------------------------------------------------------------------

    @property
    def settings(self) -> "Settings":
        if self._settings is None:
            self._settings = Settings()
        return self._settings

    def reload(self) -> "Settings":
        """强制重新加载 Settings（用于测试或热更新）。"""
        self._settings = Settings()
        return self._settings

    # ------------------------------------------------------------------
    # Scope 配置分发
    # ------------------------------------------------------------------

    def get_scope_config(self, scope_name: str) -> dict[str, Any]:
        """返回某个 scope 对应的配置字典。

        预置的 scope 映射：
        - "github"   -> GitHub App 相关配置
        - "llm"      -> LLM 相关配置
        - "database" -> 数据库 / 缓存相关配置
        - "core"     -> 应用核心配置
        """
        presets: dict[str, Callable[["Settings"], dict[str, Any]]] = {
            "github": lambda s: {
                "app_id": s.github_app_app_id,
                "private_key": s.github_app_private_key,
                "webhook_secret": s.github_app_webhook_secret,
                "installation_id": s.github_app_installation_id,
            },
            "llm": lambda s: {
                "provider": s.llm_provider,
                "api_key": s.llm_api_key,
                "model": s.llm_model,
            },
            "database": lambda s: {
                "url": s.database_url,
                "redis_url": s.redis_url,
            },
            "core": lambda s: {
                "app_name": s.app_name,
                "debug": s.debug,
                "deployment_mode": s.deployment_mode,
            },
        }

        # 优先使用预置映射
        if scope_name in presets:
            return presets[scope_name](self.settings)

        # 否则查找自定义 scope，按 prefix 取值
        scope = self._scopes.get(scope_name)
        if scope is not None:
            # 库里存的全部键都算数:有的 scope(比如 harness-env)本来就不预设字段名
            data: dict[str, Any] = dict(self._stored.get(scope_name, {}))
            for field_name in scope.required_keys + scope.optional_keys:
                val = self._scope_value(scope, field_name)
                if val is not None:
                    data[field_name] = val
            return data

        raise KeyError(f"Unknown scope: {scope_name!r}")

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _field_to_env_key(prefix: str, field_name: str) -> str:
        """将 prefix + field_name 转换为 Settings 属性名。

        例: prefix="GITHUB_APP_", field_name="app_id"
          -> "github_app_app_id"
        """
        # prefix 去掉末尾下划线，与 field_name 拼接后统一小写
        clean_prefix = prefix.rstrip("_").lower()
        return f"{clean_prefix}_{field_name}"

    def _resolve_settings_key(self, scope: ScopeDefinition, field_name: str) -> str:
        """根据 scope 的 prefix 解析出 Settings 属性名。"""
        if scope.prefix:
            return self._field_to_env_key(scope.prefix, field_name)
        return field_name

    def _dotenv_values(self) -> dict[str, str]:
        """读 .env 里那些 Settings 没声明的键。

        Settings 只会把**已声明**的字段收进模型,插件自己声明的新 scope 拿不到值。
        这里把同一份文件再读一遍,让"插件声明了什么,平台就读得出来什么"。
        """
        raw = self.settings.model_config.get("env_file") or ".env"
        path = Path(raw) if isinstance(raw, str) else Path(".env")
        if not path.exists():
            return {}
        try:
            return {k: v for k, v in dotenv_values(path).items() if v is not None}
        except Exception:  # noqa: BLE001 - 读不到就是没有,不因此起不来
            return {}

    def apply_stored(self, stored: dict[str, dict[str, str]]) -> None:
        """装上从库里读出来的那一份覆盖。"""
        self._stored = {scope: dict(values) for scope, values in stored.items()}

    def stored(self, scope_name: str) -> dict[str, str]:
        return dict(self._stored.get(scope_name, {}))

    def all_stored(self) -> dict[str, dict[str, str]]:
        return {scope: dict(values) for scope, values in self._stored.items()}

    def _scope_value(self, scope: ScopeDefinition, field_name: str) -> Any:
        """一个 scope 字段的值:库里存的 → Settings → 进程环境 → .env。

        库排在最前面:人在页面上填过的值,不该被某次部署的环境变量悄悄盖掉。
        """
        stored = self._stored.get(scope.name, {})
        if field_name in stored:
            return stored[field_name]

        settings_key = self._resolve_settings_key(scope, field_name)
        value = getattr(self.settings, settings_key, None)
        if value is not None and value != "":
            return value

        env_key = f"{scope.prefix}{field_name}".upper()
        if env_key in os.environ:
            return os.environ[env_key]
        return self._dotenv_values().get(env_key)

    # ------------------------------------------------------------------
    # 校验
    # ------------------------------------------------------------------

    def validate_scope(self, scope_name: str) -> list[str]:
        """验证 Scope 配置是否完整。返回缺失的必需配置项列表。

        Returns:
            缺失的配置项列表，如 ``["GITHUB_APP_APP_ID", "GITHUB_APP_PRIVATE_KEY"]``。
            如果没有缺失，返回空列表 ``[]``。
        """
        # 预置 scope
        presets_required: dict[str, list[str]] = {
            "github": [
                "github_app_app_id",
                "github_app_private_key",
                "github_app_webhook_secret",
                "github_app_installation_id",
            ],
            "llm": ["llm_api_key"],
            "database": ["database_url", "redis_url"],
            "core": ["app_name"],
        }

        if scope_name in presets_required:
            s = self.settings
            missing: list[str] = []
            for key in presets_required[scope_name]:
                val = getattr(s, key, None)
                if val is None or val == "":
                    missing.append(key.upper())
            return missing

        scope = self._scopes.get(scope_name)
        if scope is None:
            raise KeyError(f"Unknown scope: {scope_name!r}")

        missing = []
        for field_name in scope.required_keys:
            if self._scope_value(scope, field_name) in (None, ""):
                # 返回环境变量风格的名称（大写），人照着它去补
                env_name = f"{scope.prefix}{field_name}".upper()
                missing.append(env_name)
        return missing


class Settings(BaseSettings):
    """统一配置管理器。自动从 .env 读取所有配置，并按 scope 分发。"""

    # ---- 应用配置 ----
    app_name: str = "gwei"
    debug: bool = False

    # ---- 数据库配置 ----
    database_url: str = "postgresql+asyncpg://gwei:gwei@localhost:5432/gwei"
    redis_url: str = "redis://localhost:6379/0"

    # ---- LLM 配置 ----
    llm_provider: str = "litellm"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o"
    llm_base_url: str = ""  # OpenAI 兼容自定义端点（如自建 vLLM/one-api），空则用官方默认

    # ---- GitHub App 配置（统一 GITHUB_APP_ 前缀） ----
    github_app_app_id: str = ""
    github_app_private_key: str = ""       # PEM 格式私钥
    github_app_webhook_secret: str = ""
    github_app_installation_id: int = 0

    # ---- 部署配置 ----
    deployment_mode: str = "saas"  # saas or self-hosted

    # ---- 租户 ----
    default_tenant_slug: str = "default"  # webhook 事件的缺省租户(多租户映射接入前)

    # ---- 控制台鉴权 ----
    # token:tenant:actor:scope,逗号分隔;tenant 写 * 表示不限租户;空 = 不鉴权
    api_tokens: str = ""

    # ---- Harness ----
    # 在工作区里跑一条命令,把一次事故交给外部 agent;{workspace} 会被替换成真实路径。
    # 边界由这条命令决定(docker run / ssh ...),平台不会替你在宿主机上直接跑。留空 = 不用。
    harness_command: str = ""
    harness_timeout_s: int = 1800
    harness_workspace_root: str = "var/incidents"
    harness_token: str = ""  # harness 用的控制台令牌,从 api_tokens 里发一个给它
    platform_base_url: str = "http://127.0.0.1:8000"  # harness 访问出口用的地址

    # ---- 出口 ----
    # 一个租户每小时能通过出口改几次世界;0 表示不限。循环搬进沙箱后,平台只能数次数。
    agent_max_exits_per_hour: int = 20

    # ---- 变更单元 ----
    default_binding: str = "github"  # 效果执行的下游目标;多目标解析前只有一个
    alertmanager_webhook_token: str = ""  # 监控信号入口的共享令牌;空 = 拒绝接收
    change_ledger_backend: str = "db"  # db(业务库)| file(演示与离线调试)
    change_ledger_path: str = "var/change-ledger.jsonl"  # file 后端的落盘位置

    # .env 可能包含部署侧附加变量（如 prod 密码），容忍未知键避免启动崩溃
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


# 全局 ConfigManager 实例
config = ConfigManager()
