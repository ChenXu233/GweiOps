# engine/plugin_manager/scopes.py
"""插件的配置声明与下发 —— 让进程外插件也能拿到自己的那几项配置。

进程内插件用代码声明配置(`config.register_scope` / `register_model_scope`),核心
导入它之后才知道它要什么。进程外插件没有代码可导入,声明只能落在清单里:

    scopes:
      adapter-acme:
        prefix: ACME_
        required: [token]
        optional: [base_url]

同样的声明,核心做两件事:

1. **进配置表**(`register_manifest_scopes`):控制台的设置页因此列得出字段、
   `validate_scope` 说得出缺哪一项。字段名与进程内插件一致——两边要的是同一组事实。
2. **把值推下去**(`push`):插件的进程不在核心的内存里,`config.get_scope_config()`
   在插件进程里读不到任何东西,值只能由核心送过去。推的时机是 on_startup 之后、
   以及人改完配置之后;一次推一个 scope 的全量值,不做增量——增量会让"删掉一个键"
   与"键未改"在插件侧长得一样。

进程内插件不实现 `configure` 就不推:它自己读得到配置表,再送一份只是两份会漂移的事实。
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from engine.shared.config import config

from .manifest import Manifest

logger = logging.getLogger(__name__)


def register_manifest_scopes(manifest: Manifest) -> list[str]:
    """把清单里的 scopes 块登记进配置表,返回这次新登记的 scope 名。

    同名 scope 已经存在时**不覆盖**:那是插件自己在代码里注册的(带模型、带字段
    说明),比清单里这份粗的声明更准。清单在进程内插件这里只是"也说了一遍"。
    """
    added: list[str] = []
    for name, decl in sorted(manifest.scopes.items()):
        if config.get_scope(name) is not None:
            continue
        config.register_scope(
            name=name,
            prefix=decl.prefix,
            required=list(decl.required),
            optional=list(decl.optional),
        )
        added.append(name)
    return added


def scope_values(manifest: Manifest, tenant: str = "") -> list[dict[str, Any]]:
    """单个插件各 scope 此刻的值与缺项。缺项说得出"该去填哪个环境变量"。"""
    out: list[dict[str, Any]] = []
    for name in sorted(manifest.scopes):
        try:
            values = config.get_scope_config(name, tenant)
            missing = config.validate_scope(name, tenant)
        except KeyError:  # 声明没登记进配置表(手工构造的清单),推空值,不炸
            values, missing = {}, []
        out.append(
            {
                "scope": name,
                "config": {str(k): str(v) for k, v in values.items() if v != ""},
                "missing": missing,
            }
        )
    return out


async def push(
    instance: Any, manifest: Manifest, tenant: str = ""
) -> list[str]:
    """把声明的配置推给一个实例,返回失败说明(空 = 全推到了)。

    插件没实现 `configure` 就不推。失败不让调用方崩:插件照常在跑,差别只是它
    手里是旧配置——这件事要进日志与页面,但不能让改配置的人以为整件事失败了。
    """
    handler = getattr(instance, "configure", None)
    if handler is None or not manifest.scopes:
        return []

    failures: list[str] = []
    for item in scope_values(manifest, tenant):
        try:
            outcome = handler(item["scope"], item["config"], item["missing"])
            if hasattr(outcome, "__await__"):
                await outcome
        except Exception as e:  # noqa: BLE001 - 一个 scope 推失败不拦住其余的
            logger.warning(
                "配置没推给 %s(%s): %s", manifest.name, item["scope"], e
            )
            failures.append(f"{item['scope']}: {e}")
    return failures


async def push_all(
    instances: Iterable[tuple[Any, Manifest, str]],
) -> dict[str, str]:
    """按 (实例, 清单, 租户) 推一圈,返回 清单名 -> 失败说明。

    租户取实例自己的,不是调用方的:一个绑在租户 A 上的实例该收到 A 的配置,
    调用方是谁不影响这件事。
    """
    failures: dict[str, str] = {}
    for instance, manifest, tenant in instances:
        problems = await push(instance, manifest, tenant)
        if problems:
            failures[manifest.name] = ";".join(problems)
    return failures


__all__ = ["push", "push_all", "register_manifest_scopes", "scope_values"]
