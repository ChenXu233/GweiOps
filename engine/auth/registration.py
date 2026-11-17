# engine/auth/registration.py
"""谁能自己注册进来 —— 策略、验证码与一次性链接。

注册在**自部署**与 **SaaS** 里都要有(同一个 Nuxt 应用,同一套账号),但默认关着:
一台已经跑起来的实例不该因为升级就开始接受陌生人。开关落在配置里,租户能在
控制台里覆盖;能注册的方式也各自可关。

几件不做会出事的事,写在这里:

- **核验码只存哈希**,和会话令牌一样:库被看到也换不出能用的码。
- **试错有上限**。没有上限的六位数字,几分钟就能撞开。
- **发码有频率上限**,否则核验通道就成了别人刷短信的工具。
- **已经有密码的账号不能靠验证码直接进**(见 `verify_password_reset`):
  不然拿到手机号的人就能把账号改成自己的。
- 没配核验通道时,不是静默跳过核验,而是**拒绝**,并且说清该配什么。
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass, field

from engine.shared.config import config
from engine.shared.system_scopes import register_system_scopes

# 读取方不假设 app 已经启动过:scope 没在就补注册,幂等
register_system_scopes()

METHODS = ("email", "phone", "oidc")

# 收件人一小时内最多索取几条验证码。放在进程内存里:限流是为了挡住刷,
# 进程重启丢掉几个计数器比引入一个强依赖更划算。
_RATE: dict[str, list[float]] = {}


@dataclass(frozen=True)
class Policy:
    """这个租户现在允许怎么注册。所有字段都参与"能不能进"的判断。"""

    enabled: bool
    methods: tuple[str, ...]
    requires_verification: bool
    default_role: str
    trust_invited: bool
    # 空 = 自助注册的人自己建一个工作区;给了 slug = 落进那一个(单租户自部署那台)
    target_tenant: str
    # 自助注册建工作区时给什么角色。落到 `target_tenant` 时用的是 `default_role`。
    signup_role: str
    code_ttl_minutes: int
    reset_ttl_minutes: int
    test_code: str
    max_attempts: int
    rate_limit: int
    oidc: dict = field(default_factory=dict)

    def allows(self, method: str) -> bool:
        return self.enabled and method in self.methods

    def describe(self) -> list[str]:
        """给界面的那句话:现在能用什么方式进。"""
        labels = {"email": "邮箱", "phone": "手机号", "oidc": "统一身份"}
        return [labels[m] for m in self.methods]


def _flag(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "是")


def _int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _methods(raw, *, oidc_ready: bool) -> tuple[str, ...]:
    picked = [m.strip().lower() for m in str(raw or "").split(",") if m.strip()]
    out = []
    for method in picked:
        if method not in METHODS or method in out:
            continue
        # 没配好的 OIDC 不该出现在"能用的方式"里:点了必然失败的门不如不显
        if method == "oidc" and not oidc_ready:
            continue
        out.append(method)
    return tuple(out)


def oidc_configured() -> bool:
    s = config.get_scope_config("oidc")
    return bool(s.get("oidc_issuer") and s.get("oidc_client_id") and s.get("oidc_client_secret"))


def policy_for(tenant: str = "") -> Policy:
    """生效策略:全局配置打底,租户库里那一份逐键覆盖。

    逐键而不是整份:租户只想改"默认角色",不该被迫把核验方式也抄一遍。
    """
    # 生效值取自 registration / oidc 两个 scope:库覆盖、Settings、环境与 .env
    # 已按同一套优先级合并好,这里不再自己拼第二遍。
    scope = config.get_scope_config("registration", tenant)
    s = config.settings
    # 这四个只能靠环境变量(部署期决定,运行期改不了):trust_invited / tenant /
    # signup_role 定"这台实例的注册怎么落地",test_code 只给自部署联调用。
    raw = {
        "registration_enabled": scope.get("registration_enabled") or s.registration_enabled,
        "registration_methods": scope.get("registration_methods") or s.registration_methods,
        "registration_requires_verification": scope.get("registration_requires_verification")
        if scope.get("registration_requires_verification") is not None
        else s.registration_requires_verification,
        "registration_default_role": scope.get("registration_default_role") or s.registration_default_role,
        "registration_trust_invited": s.registration_trust_invited,
        "registration_tenant": s.registration_tenant,
        "registration_signup_role": s.registration_signup_role,
        "registration_code_ttl_minutes": s.registration_code_ttl_minutes,
        "registration_reset_ttl_minutes": s.registration_reset_ttl_minutes,
        "registration_test_code": s.registration_test_code,
        "registration_max_attempts": s.registration_max_attempts,
        "registration_rate_limit": s.registration_rate_limit,
    }
    stored = config.stored("registration", tenant)
    merged = {**raw, **{k: v for k, v in stored.items() if k in raw and v != ""}}

    oidc_scope = config.get_scope_config("oidc", tenant)
    oidc = {
        "configured": oidc_configured(),
        "label": str(oidc_scope.get("oidc_button_label") or s.oidc_button_label),
        "auto_create": bool(oidc_scope.get("oidc_auto_create", s.oidc_auto_create)),
        "default_role": str(
            oidc_scope.get("oidc_default_role") or merged["registration_default_role"]
        ),
    }
    return Policy(
        enabled=_flag(merged["registration_enabled"]),
        methods=_methods(merged["registration_methods"], oidc_ready=oidc["configured"]),
        requires_verification=_flag(merged["registration_requires_verification"]),
        default_role=str(merged["registration_default_role"] or "viewer"),
        trust_invited=_flag(merged["registration_trust_invited"]),
        target_tenant=str(merged["registration_tenant"] or ""),
        signup_role=str(merged["registration_signup_role"] or "owner"),
        code_ttl_minutes=max(1, _int(merged["registration_code_ttl_minutes"], 15)),
        reset_ttl_minutes=max(1, _int(merged["registration_reset_ttl_minutes"], 30)),
        test_code=str(merged["registration_test_code"] or ""),
        max_attempts=max(1, _int(merged["registration_max_attempts"], 5)),
        rate_limit=max(0, _int(merged["registration_rate_limit"], 5)),
        oidc=oidc,
    )


# ---------------------------------------------------------------------------
# 验证码
# ---------------------------------------------------------------------------


def normalize_contact(target: str) -> str:
    return (target or "").strip().lower()


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_code(target: str, purpose: str, code: str) -> str:
    """码的哈希绑上收件人与用途:一个码不能挪去干别的事。"""
    return hashlib.sha256(f"{target}|{purpose}|{code}".encode("utf-8")).hexdigest()


def new_link_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode("utf-8")).hexdigest()


def rate_allows(target: str, policy: Policy) -> bool:
    """发码频率。limit=0 表示不限。"""
    if policy.rate_limit <= 0:
        return True
    now = time.time()
    stamps = [t for t in _RATE.get(target, []) if now - t < 3600]
    _RATE[target] = stamps
    return len(stamps) < policy.rate_limit


def rate_record(target: str) -> None:
    _RATE.setdefault(target, []).append(time.time())


def rate_forget(target: str) -> None:
    _RATE.pop(target, None)


__all__ = [
    "METHODS",
    "Policy",
    "hash_code",
    "new_code",
    "new_link_token",
    "normalize_contact",
    "oidc_configured",
    "policy_for",
    "rate_allows",
    "rate_forget",
    "rate_record",
]
