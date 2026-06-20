# plugins/builtin/adapters/github-app/config.py
from engine.shared.config import config


class GitHubAppConfig:
    """GitHub App Adapter 配置（内部 Scope）。"""

    SCOPE_NAME = "adapter-github-app"
    SCOPE_PREFIX = "GITHUB_APP_"
    REQUIRED_FIELDS = ["app_id", "private_key"]
    OPTIONAL_FIELDS = ["webhook_secret", "installation_id"]

    def __init__(self):
        # 注册 Scope
        config.register_scope(
            name=self.SCOPE_NAME,
            prefix=self.SCOPE_PREFIX,
            required=self.REQUIRED_FIELDS,
            optional=self.OPTIONAL_FIELDS,
        )
        self._config = config.get_scope_config(self.SCOPE_NAME)

    @property
    def app_id(self) -> str:
        return self._config.get("app_id", "")

    @property
    def private_key(self) -> str:
        return self._config.get("private_key", "")

    @property
    def webhook_secret(self) -> str:
        return self._config.get("webhook_secret", "")

    @property
    def installation_id(self) -> int:
        return self._config.get("installation_id", 0)

    def validate(self) -> list[str]:
        """验证配置是否完整。"""
        return config.validate_scope(self.SCOPE_NAME)
