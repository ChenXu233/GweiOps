# engine/shared/config.py
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pydantic_settings import BaseSettings


@dataclass
class ScopeDefinition:
    """定义一个配置 scope，用于按功能域分发配置。"""

    name: str
    description: str = ""
    required_keys: list[str] = field(default_factory=list)
    validator: Optional[Callable[["Settings"], bool]] = None

    def validate(self, settings: "Settings") -> bool:
        """校验该 scope 所需的配置是否齐全。"""
        for key in self.required_keys:
            value = getattr(settings, key, None)
            if value is None or value == "":
                return False
        if self.validator:
            return self.validator(settings)
        return True


class ConfigManager:
    """全局配置管理器，支持注册 scope 并按 scope 分发配置。"""

    def __init__(self) -> None:
        self._scopes: dict[str, ScopeDefinition] = {}
        self._settings: Optional[Settings] = None

    # ------------------------------------------------------------------
    # Scope 注册
    # ------------------------------------------------------------------

    def register_scope(self, scope: ScopeDefinition) -> None:
        """注册一个配置 scope。重复注册同名 scope 会被覆盖。"""
        self._scopes[scope.name] = scope

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

        # 否则查找自定义 scope，返回 Settings 全量字典中匹配 required_keys 的子集
        scope = self._scopes.get(scope_name)
        if scope is not None:
            data = self.settings.model_dump()
            return {k: data[k] for k in scope.required_keys if k in data}

        raise KeyError(f"Unknown scope: {scope_name!r}")

    # ------------------------------------------------------------------
    # 校验
    # ------------------------------------------------------------------

    def validate_scope(self, scope_name: str) -> bool:
        """校验某个 scope 的配置是否有效。"""
        # 预置 scope 无额外校验，只检查对应字段非空
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
            for key in presets_required[scope_name]:
                val = getattr(s, key, None)
                if val is None or val == "" or val == 0:
                    return False
            return True

        scope = self._scopes.get(scope_name)
        if scope is None:
            raise KeyError(f"Unknown scope: {scope_name!r}")
        return scope.validate(self.settings)


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
