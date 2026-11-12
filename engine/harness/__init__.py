# engine/harness/__init__.py
"""外部 harness 适配:在工作区里跑一条命令,收回一份报告。"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from engine.shared.config import config

from . import workspace
from .adapter import REPORT_NAME, HarnessResult, build_env, build_task, run_harness
from .workspace import WorkspaceError, collect, prepare, repo_of, workspace_of

# 形状写在类型里:写入时 validate_values 会拿模型验一遍,坏值当场 422,不等到起容器才炸。
# 空串一律允许——"还没填"不是错误,缺什么由 validate_scope 单独报。
ApiKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^$|^[A-Za-z0-9._\-]{8,256}$"),
]
BaseUrl = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^$|^https?://\S{1,200}$"),
]
ModelName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^$|^[A-Za-z0-9][A-Za-z0-9._:\-]{0,63}$"),
]


class HarnessEnvSettings(BaseModel):
    """交给 harness 的环境变量:声明已知的,允许未知的。

    dsh 只认 DEEPSEEK_API_KEY 这种名字,平台不替它猜——所以模型放开额外键
    (extra="allow");但声明出来的字段有类型与形状约束,写错了存不进去。

    回显规则也在字段上:密钥永不回显,只告诉你"设过了";模型名与地址不是秘密。
    """

    model_config = ConfigDict(extra="allow")

    deepseek_api_key: ApiKey = Field(
        "",
        description="DeepSeek API Key,形如 sk- 开头的一串字符",
        json_schema_extra={"expose": "never", "read_scope": "operate"},
    )
    deepseek_base_url: BaseUrl = Field(
        "",
        description="接口地址,需要以 http:// 或 https:// 开头",
        json_schema_extra={"expose": "always"},
    )
    model: ModelName = Field(
        "",
        description="模型名,例如 deepseek-flash",
        json_schema_extra={"expose": "always"},
    )


# 凭据不由部署方进容器手配:写进这个 scope,平台起容器时注入成大写环境变量。
config.register_model_scope("harness-env", HarnessEnvSettings, prefix="HARNESS_ENV_")

__all__ = [
    "REPORT_NAME",
    "HarnessResult",
    "WorkspaceError",
    "build_env",
    "build_task",
    "collect",
    "prepare",
    "repo_of",
    "run_harness",
    "workspace",
    "workspace_of",
    "HarnessEnvSettings",
]
