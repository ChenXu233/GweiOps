# engine/shared/system_scopes.py
"""系统域的配置 scope。

有一批配置(注册策略、核验通道、OIDC、配额)历史上只能靠环境变量,页面上一片
"未设置"也改不了——它们没有被注册成 scope,`GET /api/settings/scopes` 列不出来,
`PUT` 也写不进去。这一份把平台自己那几块按功能域注册成模型 scope,规则与插件的
完全一样:字段、必填、回显都声明在模型里,读取优先级也是同一套
(库 → Settings → 进程环境 → .env)。

`database`、`app_name` 这类**进程起来之前就得有**的键不在任何 scope 里:页面上
改了也救不了没起来的进程,把它们摆出来只是让人白填一遍。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from engine.shared.config import config


class RegistrationScope(BaseModel):
    """自助注册的策略。租户在设置页逐键覆盖,生效值由 policy_for 合并。"""

    model_config = ConfigDict(extra="ignore")

    registration_enabled: bool = Field(
        False,
        description="允许自助注册;关掉之后只有管理员能在成员页加人",
        json_schema_extra={"expose": "always"},
    )
    registration_methods: str = Field(
        "email",
        description="注册方式,逗号分隔:email(邮箱+密码+验证码) | phone(手机号+短信码) | oidc(统一身份)",
        json_schema_extra={"expose": "always"},
    )
    registration_requires_verification: bool = Field(
        True,
        description="注册必须过验证码;关掉就是填了就能进,只建议在完全内网时用",
        json_schema_extra={"expose": "always"},
    )
    registration_default_role: str = Field(
        "viewer",
        description="新注册用户自动接上的角色 key",
        json_schema_extra={"expose": "always"},
    )
    registration_public_base_url: str = Field(
        "",
        description="邮件链接与 OIDC 回跳落到的前台地址;留空按请求 Host 推(反代后面常推错)",
        json_schema_extra={"expose": "always"},
    )


class EmailScope(BaseModel):
    """邮箱核验通道。没有通道时注册核验如实拒绝,不静默跳过。"""

    model_config = ConfigDict(extra="ignore")

    email_provider: str = Field(
        "console",
        description="发信方式:console(打到日志) | smtp | resend | webhook",
        json_schema_extra={"expose": "always"},
    )
    email_from: str = Field(
        "",
        description="发件人地址;resend 必填,smtp 缺省用 smtp_user",
        json_schema_extra={"expose": "always"},
    )
    smtp_host: str = Field(
        "", description="SMTP 主机", json_schema_extra={"expose": "always"}
    )
    smtp_port: int = Field(
        587, description="SMTP 端口", json_schema_extra={"expose": "always"}
    )
    smtp_user: str = Field(
        "", description="SMTP 用户名", json_schema_extra={"expose": "always"}
    )
    smtp_password: str = Field(
        "", description="SMTP 密码", json_schema_extra={"expose": "never"}
    )
    smtp_starttls: bool = Field(
        True, description="连接后先 STARTTLS", json_schema_extra={"expose": "always"}
    )
    resend_api_key: str = Field(
        "", description="Resend API Key;选 resend 时必填", json_schema_extra={"expose": "never"}
    )
    # 邮箱的 webhook 与短信共用一个地址,请求体里用 channel 区分
    sms_webhook_url: str = Field(
        "",
        description="短信核验的转发地址(webhook);邮箱的 webhook 通道也发到这里,靠 channel 区分",
        json_schema_extra={"expose": "always"},
    )
    sms_webhook_token: str = Field(
        "", description="发给 webhook 的令牌,以 X-Gwei-Token 头携带", json_schema_extra={"expose": "never"}
    )


class SmsScope(BaseModel):
    """手机号核验通道。短信商的 API 各家不一样,平台不替它猜,只认 webhook。"""

    model_config = ConfigDict(extra="ignore")

    sms_provider: str = Field(
        "webhook",
        description="发码方式:console(打到日志) | webhook(转发给你的短信服务)",
        json_schema_extra={"expose": "always"},
    )
    sms_webhook_url: str = Field(
        "", description="转发地址:引擎 POST {channel, to, code, purpose, expires_in}", json_schema_extra={"expose": "always"}
    )
    sms_webhook_token: str = Field(
        "", description="以 X-Gwei-Token 头发给 webhook 的令牌", json_schema_extra={"expose": "never"}
    )


class OidcScope(BaseModel):
    """OIDC 单点登录。没配全 issuer/client_id/client_secret 时登录页不出这个选项。"""

    model_config = ConfigDict(extra="ignore")

    oidc_issuer: str = Field(
        "", description="身份提供方的 issuer 地址", json_schema_extra={"expose": "always"}
    )
    oidc_client_id: str = Field(
        "", description="OIDC 客户端 ID", json_schema_extra={"expose": "always"}
    )
    oidc_client_secret: str = Field(
        "", description="OIDC 客户端密钥", json_schema_extra={"expose": "never"}
    )
    oidc_scopes: str = Field(
        "openid email profile", description="授权时请求的 scope", json_schema_extra={"expose": "always"}
    )
    oidc_button_label: str = Field(
        "用统一身份登录", description="登录页上这个按钮的文字", json_schema_extra={"expose": "always"}
    )
    oidc_auto_create: bool = Field(
        True, description="首次 OIDC 登录时按注册策略自动建号", json_schema_extra={"expose": "always"}
    )
    oidc_default_role: str = Field(
        "", description="OIDC 新号的默认角色;留空跟 registration_default_role 一致", json_schema_extra={"expose": "always"}
    )


class LlmScope(BaseModel):
    """LLM 调用的凭据与模型。key 没配时真实调用关闭,只走降级路径。"""

    model_config = ConfigDict(extra="ignore")

    llm_provider: str = Field(
        "litellm", description="调用封装:litellm(OpenAI 兼容)", json_schema_extra={"expose": "always"}
    )
    llm_api_key: str = Field(
        "", description="模型服务的 API Key;留空 = 不启用真实调用", json_schema_extra={"expose": "never"}
    )
    llm_model: str = Field(
        "gpt-4o", description="模型名", json_schema_extra={"expose": "always"}
    )
    llm_base_url: str = Field(
        "",
        description="OpenAI 兼容自定义端点(如自建 vLLM / one-api);留空用官方默认",
        json_schema_extra={"expose": "always"},
    )


class QuotaScope(BaseModel):
    """配额限量,写法与配额表一致:`2000/30d`。没声明的资源 = 不限。"""

    model_config = ConfigDict(extra="allow")

    issues: str = Field(
        "", description="议题,数量/窗口,例如 2000/30d;留空不限", json_schema_extra={"expose": "always"}
    )
    llm_tokens: str = Field(
        "", description="LLM token 用量,数量/窗口;留空不限", json_schema_extra={"expose": "always"}
    )
    agent_runs: str = Field(
        "", description="agent 执行次数,数量/窗口,例如 500/5h;留空不限", json_schema_extra={"expose": "always"}
    )


def register_system_scopes() -> None:
    """注册系统域 scope。重复导入不重复注册;同名已有(不该发生)也不覆盖。

    单测直接 import 读取方模块而不经 app 启动,所以读取方也调这个函数:
    scope 注册是幂等的,多调一次没有第二份。"""
    for name, model in (
        ("registration", RegistrationScope),
        ("email", EmailScope),
        ("sms", SmsScope),
        ("oidc", OidcScope),
        ("llm", LlmScope),
        ("quota", QuotaScope),
    ):
        if config.get_scope(name) is None:
            config.register_model_scope(name, model)


__all__ = ["register_system_scopes"]
