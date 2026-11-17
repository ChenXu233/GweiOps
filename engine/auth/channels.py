# engine/auth/channels.py
"""把验证码送出去 —— 邮箱走 SMTP / Resend / 转发,手机号走 webhook。

**平台不猜短信商的 API**。短信网关的地址、鉴权与报文各家都不一样,在这里写死
一家等于把其余家挡在门外。所以手机号的通道是一个 webhook:引擎 POST 一包
`{"to", "code", "purpose", "expires_in"}`,由运维那边接自己的短信服务。
这不是省事,是把"谁负责发短信"放回它该在的地方。

没配通道时**不静默跳过核验**:抛 `ChannelError`,由接口如实回 503 并说清配什么。
一个自称核验过、其实什么都没发的注册系统,比没有核验更危险。

邮箱与短信之外都只用标准库(smtplib / urllib),不为发一封信引一个 SDK。
"""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage

from engine.shared.config import config
from engine.shared.system_scopes import register_system_scopes

# 通道的值走 email / sms 两个 scope(库覆盖 → Settings → 环境);读取方自己保证
# scope 已注册,单测不经 app 启动也能拿到同一套优先级
register_system_scopes()

logger = logging.getLogger(__name__)

PURPOSE_LABELS = {
    "register": "注册核验",
    "reset": "重置密码",
}


class ChannelError(RuntimeError):
    """通道没配或发不出去。message 是给人看的,要能照着它去配。"""


def _subject(purpose: str) -> str:
    return f"{config.settings.app_name} {PURPOSE_LABELS.get(purpose, '验证码')}"


def _body(
    code: str, purpose: str, ttl_minutes: int, *, link_name: str = "", lead: str = ""
) -> str:
    """验证码与一次性链接走同一个信道、同一个函数 —— 差别只是正文这句。"""
    label = PURPOSE_LABELS.get(purpose, "验证码")
    if link_name:
        return (
            f"{lead or '点开下面的链接'}:\n\n{code}\n\n"
            f"链接 {ttl_minutes} 分钟内有效,且只能用一次。\n\n"
            "如果不是你本人操作,忽略这封信即可 —— 没有这个链接,谁也不能动这个账号。\n"
        )
    return (
        f"你的{label}验证码是 {code},{ttl_minutes} 分钟内有效。\n\n"
        "如果不是你本人操作,忽略这封信即可 —— 没有这个码,谁也不能动这个账号。\n"
    )


# ---------------------------------------------------------------------------
# 邮箱
# ---------------------------------------------------------------------------


def _smtp(to: str, code: str, purpose: str, ttl: int, **kw) -> None:
    s = config.get_scope_config("email")
    if not s.get("smtp_host"):
        raise ChannelError("邮箱核验要配 smtp_host(设置页的 email scope,以及 smtp_user / smtp_password / email_from)")
    message = EmailMessage()
    message["Subject"] = _subject(purpose)
    message["From"] = s.get("email_from") or s.get("smtp_user")
    message["To"] = to
    message.set_content(_body(code, purpose, ttl, **kw))
    with smtplib.SMTP(s.get("smtp_host"), int(s.get("smtp_port") or 587), timeout=15) as client:
        if s.get("smtp_starttls", True):
            client.starttls()
        if s.get("smtp_user"):
            client.login(s.get("smtp_user"), s.get("smtp_password"))
        client.send_message(message)


def _resend(to: str, code: str, purpose: str, ttl: int, **kw) -> None:
    s = config.get_scope_config("email")
    if not s.get("resend_api_key") or not s.get("email_from"):
        raise ChannelError("Resend 要配 resend_api_key 与 email_from(设置页的 email scope)")
    payload = json.dumps(
        {
            "from": s.get("email_from"),
            "to": [to],
            "subject": _subject(purpose),
            "text": _body(code, purpose, ttl, **kw),
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {s.get('resend_api_key')}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as resp:  # noqa: S310 - 地址是常量
        if resp.status >= 300:
            raise ChannelError(f"Resend 回了 {resp.status}")


def _post(url: str, payload: dict, token: str = "") -> None:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Gwei-Token"] = token
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:  # noqa: S310 - 地址由运维配
            if resp.status >= 300:
                raise ChannelError(f"投递通道回了 {resp.status}")
    except urllib.error.URLError as exc:
        raise ChannelError(f"投递通道连不上:{exc.reason}") from exc


def _email_console(to: str, code: str, purpose: str, ttl: int, **kw) -> None:
    # 自部署最后一公里:没有邮件服务也能把流程跑通。码进日志,并明说这是日志。
    logger.warning(
        "邮箱核验码(未配邮件通道,直接打在日志里):to=%s purpose=%s code=%s", to, purpose, code
    )


def _email_webhook(to: str, code: str, purpose: str, ttl: int, **kw) -> None:
    s = config.get_scope_config("email")
    url = s.get("sms_webhook_url")
    if not url:
        raise ChannelError("邮箱走 webhook 要配 sms_webhook_url(设置页的 email scope)")
    _post(
        url,
        {"channel": "email", "to": to, "code": code, "purpose": purpose, "expires_in": ttl},
        s.get("sms_webhook_token"),
    )


EMAIL_SENDERS = {
    "console": _email_console,
    "smtp": _smtp,
    "resend": _resend,
    "webhook": _email_webhook,
}


# ---------------------------------------------------------------------------
# 手机号
# ---------------------------------------------------------------------------


def _sms_console(to: str, code: str, purpose: str, ttl: int) -> None:
    logger.warning(
        "短信核验码(未配短信通道,直接打在日志里):to=%s purpose=%s code=%s", to, purpose, code
    )


def _sms_webhook(to: str, code: str, purpose: str, ttl: int) -> None:
    s = config.get_scope_config("sms")
    if not s.get("sms_webhook_url"):
        raise ChannelError("短信走 webhook 要配 sms_webhook_url(设置页的 sms scope)")
    _post(
        s.get("sms_webhook_url"),
        {"channel": "sms", "to": to, "code": code, "purpose": purpose, "expires_in": ttl},
        s.get("sms_webhook_token"),
    )


SMS_SENDERS = {"console": _sms_console, "webhook": _sms_webhook}


# ---------------------------------------------------------------------------
# 出口
# ---------------------------------------------------------------------------


async def deliver_email(
    to: str,
    code: str,
    purpose: str,
    ttl_minutes: int,
    *,
    link_name: str = "",
    lead: str = "",
) -> None:
    """link_name 非空表示"code 里装的是一条链接" —— 重置密码走的就是这条。"""
    provider = (config.get_scope_config("email").get("email_provider") or "console").strip().lower()
    sender = EMAIL_SENDERS.get(provider)
    if sender is None:
        raise ChannelError(f"email_provider 只能是 {'/'.join(EMAIL_SENDERS)}(设置页的 email scope),收到 {provider!r}")
    # smtplib 与 urllib 都是阻塞的:放进线程,别卡住事件循环
    await asyncio.to_thread(sender, to, code, purpose, ttl_minutes, link_name=link_name, lead=lead)


async def deliver_sms(to: str, code: str, purpose: str, ttl_minutes: int) -> None:
    provider = (config.get_scope_config("sms").get("sms_provider") or "webhook").strip().lower()
    sender = SMS_SENDERS.get(provider)
    if sender is None:
        raise ChannelError(f"sms_provider 只能是 {'/'.join(SMS_SENDERS)}(设置页的 sms scope),收到 {provider!r}")
    await asyncio.to_thread(sender, to, code, purpose, ttl_minutes)


__all__ = ["ChannelError", "deliver_email", "deliver_sms"]
