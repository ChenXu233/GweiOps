# engine/shared/config.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pydantic_settings import BaseSettings


@dataclass
class ScopeDefinition:
    """定义一个配置 scope，用于按功能域分发配置。"""

    name: str
    prefix: str = ""
    description: str = ""
    required_keys: list[str] = field(default_factory=list)
    optional_keys: list[str] = field(default_factory=list)
    validator: Optional[Callable[["Settings"], bool]] = None


class ConfigManager:
    """全局配置管理器，支持注册 scope 并按 scope 分发配置。"""

    def __init__(self) -> None:
        self._scopes: dict[str, ScopeDefinition] = {}
        self._settings: Optional[Settings] = None

    # ------------------------------------------------------------------
    # Scope 注册
    # ------------------------------------------------------------------

    def register_scope(
        self,
        name: str,
        prefix: str,
        required: list[str] | None = None,
        optional: list[str] | None = None,
    ) -> None:
        """注册一个配置 scope。重复注册同名 scope 会被覆盖。

        Args:
            name:     scope 名称，例如 ``"github"``
            prefix:   环境变量前缀，例如 ``"GITHUB_APP_"``
            required: 必需的配置项字段名列表（不含前缀），例如 ``["app_id", "private_key"]``
            optional: 可选的配置项字段名列表（不含前缀）
        """
        scope = ScopeDefinition(
            name=name,
            prefix=prefix,
            required_keys=required or [],
            optional_keys=optional or [],
        )
        self._scopes[name] = scope

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

        # 否则查找自定义 scope，使用 prefix 映射获取配置
        scope = self._scopes.get(scope_name)
        if scope is not None:
            s = self.settings
            data: dict[str, Any] = {}
            all_keys = scope.required_keys + scope.optional_keys
            for field_name in all_keys:
                settings_key = self._resolve_settings_key(scope, field_name)
                val = getattr(s, settings_key, None)
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
                if val is None or val == "" or val == 0:
                    missing.append(key.upper())
            return missing

        scope = self._scopes.get(scope_name)
        if scope is None:
            raise KeyError(f"Unknown scope: {scope_name!r}")

        s = self.settings
        missing = []
        for field_name in scope.required_keys:
            settings_key = self._resolve_settings_key(scope, field_name)
            val = getattr(s, settings_key, None)
            if val is None or val == "" or val == 0:
                # 返回环境变量风格的名称（大写）
                env_name = self._field_to_env_key(scope.prefix or scope.name, field_name).upper()
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

    # ---- GitHub App 配置（统一 GITHUB_APP_ 前缀） ----
    github_app_app_id: str = ""
    github_app_private_key: str = ""       # PEM 格式私钥
    github_app_webhook_secret: str = ""
    github_app_installation_id: int = 0

    # ---- 部署配置 ----
    deployment_mode: str = "saas"  # saas or self-hosted

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def get_github_config(self) -> dict:
        """获取 GitHub App 配置。"""
        return {
            "app_id": self.github_app_app_id,
            "private_key": self.github_app_private_key,
            "webhook_secret": self.github_app_webhook_secret,
            "installation_id": self.github_app_installation_id,
        }

    def get_llm_config(self) -> dict:
        """获取 LLM 配置。"""
        return {
            "provider": self.llm_provider,
            "api_key": self.llm_api_key,
            "model": self.llm_model,
        }

    def get_database_config(self) -> dict:
        """获取数据库配置。"""
        return {
            "url": self.database_url,
            "redis_url": self.redis_url,
        }


# 全局 ConfigManager 实例
config = ConfigManager()
