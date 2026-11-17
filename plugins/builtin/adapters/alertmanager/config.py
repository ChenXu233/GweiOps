# plugins/builtin/adapters/alertmanager/config.py
from pydantic import BaseModel, Field

from engine.shared.config import config


class AlertmanagerSettings(BaseModel):
    webhook_token: str = Field(
        "",
        description="Alertmanager 投递时带的共享令牌(X-Gwei-Token 头);不填就拒收,这个端点会起工作流",
        json_schema_extra={"expose": "never"},
    )


class AlertmanagerConfig:
    """Alertmanager 适配器配置。

    Alertmanager 自己不签名,只认共享令牌;令牌为空就是不设防,所以空值等于
    "拒收",不退回某种"本机信任"。
    """

    SCOPE_NAME = "adapter-alertmanager"
    SCOPE_PREFIX = "ALERTMANAGER_"

    def __init__(self) -> None:
        config.register_model_scope(
            self.SCOPE_NAME,
            AlertmanagerSettings,
            prefix=self.SCOPE_PREFIX,
            owner="alertmanager-adapter",
        )
        raw = config.get_scope_config(self.SCOPE_NAME, config.settings.default_tenant_slug)
        self._settings = AlertmanagerSettings(**{k: v for k, v in raw.items() if v != ""})

    @property
    def token(self) -> str:
        return self._settings.webhook_token

    def validate(self) -> list[str]:
        return config.validate_scope(self.SCOPE_NAME, config.settings.default_tenant_slug)
