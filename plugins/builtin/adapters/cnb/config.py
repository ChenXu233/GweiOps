# plugins/builtin/adapters/cnb/config.py
"""CNB 适配器配置。Webhook 的鉴权头名可配:不同部署的投递头不完全一样。"""

from pydantic import BaseModel, Field

from engine.shared.config import config


class CNBSettings(BaseModel):
    base_url: str = Field(
        "https://api.cnb.cool",
        description="CNB OpenAPI 地址",
        json_schema_extra={"expose": "always"},
    )
    web_base_url: str = Field(
        "https://cnb.cool",
        description="CNB 网页端点:仓库归档下载走它,和 OpenAPI 不是同一个域名",
        json_schema_extra={"expose": "always"},
    )
    webhook_token: str = Field(
        "",
        description="Webhook 共享令牌:CNB 投递时带的密钥,必须一致;不填就拒收投递",
        json_schema_extra={"expose": "never"},
    )
    webhook_header: str = Field(
        "X-Cnb-Token",
        description="投递令牌所在的请求头名;按你的 CNB Webhook 配置填",
        json_schema_extra={"expose": "always"},
    )
    token: str = Field(
        "",
        description="访问令牌:回评、读合并请求要用;只接合并事件可以先不填",
        json_schema_extra={"expose": "never"},
    )


class CNBConfig:
    SCOPE_NAME = "adapter-cnb"
    SCOPE_PREFIX = "CNB_"

    def __init__(self) -> None:
        config.register_model_scope(
            self.SCOPE_NAME, CNBSettings, prefix=self.SCOPE_PREFIX, owner="cnb-adapter"
        )
        raw = config.get_scope_config(self.SCOPE_NAME, config.settings.default_tenant_slug)
        self._settings = CNBSettings(**{k: v for k, v in raw.items() if v != ""})

    @property
    def base_url(self) -> str:
        return str(self._settings.base_url).rstrip("/")

    @property
    def web_base_url(self) -> str:
        return str(self._settings.web_base_url).rstrip("/")

    @property
    def webhook_token(self) -> str:
        return self._settings.webhook_token

    @property
    def webhook_header(self) -> str:
        return self._settings.webhook_header

    @property
    def token(self) -> str:
        return self._settings.token
