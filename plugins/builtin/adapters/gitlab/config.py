# plugins/builtin/adapters/gitlab/config.py
"""GitLab 适配器配置。走平台的 scope 机制:页面能填、密钥不回显、改了不用重启。"""

from pydantic import BaseModel, Field

from engine.shared.config import config


class GitLabSettings(BaseModel):
    base_url: str = Field(
        "https://gitlab.com",
        description="GitLab 实例地址,自建实例填自己的域名",
        json_schema_extra={"expose": "always"},
    )
    webhook_secret: str = Field(
        "",
        description="Webhook 密钥:GitLab 项目 Webhook 里填的 Secret Token,必须一致;不填就拒收投递",
        json_schema_extra={"expose": "never"},
    )
    token: str = Field(
        "",
        description="访问令牌:回评、读合并请求要用;只接合并事件可以先不填",
        json_schema_extra={"expose": "never"},
    )


class GitLabConfig:
    SCOPE_NAME = "adapter-gitlab"
    SCOPE_PREFIX = "GITLAB_"

    def __init__(self) -> None:
        config.register_model_scope(self.SCOPE_NAME, GitLabSettings, prefix=self.SCOPE_PREFIX)
        raw = config.get_scope_config(self.SCOPE_NAME, config.settings.default_tenant_slug)
        self._settings = GitLabSettings(**{k: v for k, v in raw.items() if v != ""})

    @property
    def base_url(self) -> str:
        return str(self._settings.base_url).rstrip("/")

    @property
    def webhook_secret(self) -> str:
        return self._settings.webhook_secret

    @property
    def token(self) -> str:
        return self._settings.token
