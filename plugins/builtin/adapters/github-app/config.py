# plugins/builtin/adapters/github-app/config.py
from pydantic import BaseModel, Field

from engine.shared.config import config


def normalize_pem(raw: str) -> str:
    """把 .env 里的私钥还原成 PEM。

    .env 只能放单行值：换行写成字面量 \n，这里还原成真实换行；已经是多行的原样返回。
    """
    if not raw:
        return ""
    if "\n" in raw:
        return raw
    return raw.replace("\\n", "\n")


class GitHubAppSettings(BaseModel):
    """配置形状由这里定:哪些必填、哪些能回显、回显成什么样。

    app_id 不是秘密,原样给出去;私钥与 webhook 密钥永不回显——
    页面上只需要知道"设过了",不需要看到值。
    """

    app_id: str = Field(
        ...,
        description="GitHub App 的数字 ID,在 App 设置页能看到",
        json_schema_extra={"expose": "always"},
    )
    private_key: str = Field(
        ...,
        description="App 私钥(PEM),整段贴进来;.env 里换行写成 \\n",
        json_schema_extra={"expose": "never", "multiline": True},
    )
    webhook_secret: str = Field(
        "",
        description="Webhook 密钥:GitHub 投递的签名密钥,必须和 App 设置里填的一致;不填就拒收投递",
        json_schema_extra={"expose": "never"},
    )
    installation_id: int = Field(
        0,
        description="安装 ID,取安装页 URL 末尾的数字",
        json_schema_extra={"expose": "never"},
    )


class GitHubAppConfig:
    """GitHub App Adapter 配置（内部 Scope）。"""

    SCOPE_NAME = "adapter-github-app"
    SCOPE_PREFIX = "GITHUB_APP_"

    def __init__(self):
        config.register_model_scope(self.SCOPE_NAME, GitHubAppSettings, prefix=self.SCOPE_PREFIX)
        # 这个适配器是共享的(tenant 为空,一套 App 服务所有租户),配置只有一份。
        # 控制台把值写在调用方租户上(通常是 default),所以这里按默认租户读;
        # 读不到再落回公共值与 .env。不这样读,页面上填的东西插件永远看不见。
        raw = config.get_scope_config(self.SCOPE_NAME, config.settings.default_tenant_slug)
        # 空串按"没填"处理,让模型的默认值说话(installation_id 尤其需要)
        self._settings = GitHubAppSettings(**{k: v for k, v in raw.items() if v != ""})

    @property
    def app_id(self) -> str:
        return str(self._settings.app_id)

    @property
    def private_key(self) -> str:
        return normalize_pem(self._settings.private_key)

    @property
    def webhook_secret(self) -> str:
        return self._settings.webhook_secret

    @property
    def installation_id(self) -> int:
        return int(self._settings.installation_id)

    def validate(self) -> list[str]:
        """验证配置是否完整。

        要按同一个租户的口径验:值是从默认租户读的,校验却看公共值,
        就会出现"值明明有、启动却说缺项"这种自相矛盾的日志。
        """
        return config.validate_scope(self.SCOPE_NAME, config.settings.default_tenant_slug)
