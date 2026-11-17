# engine/ingest/source.py
"""来源适配器的契约 —— 核心对一个来源只问这几件事。

一个来源(代码托管、告警系统)由适配器插件提供,核心不认识任何一家的字段名。
适配器要能被 `POST /webhook/{source}` 接进来、被工作流当成"这条投递来自谁"来用,
必须给出下面这几样:

| 名字 | 核心拿它做什么 |
| --- | --- |
| `source` | `/webhook/<source>` 按它分发;回评按同名 binding 解析效果提供者 |
| `mentions` | 这个来源上人叫平台用的触发词(CNB 上是 `@CodeBuddy`,不是 `@gwei`) |
| `webhook_configured()` / `verify_webhook()` / `parse_webhook()` | 验签与归一化 |
| `workspace_source(repo)` | 把哪份代码、哪条分支放进工作区 |
| `list_issues(repo)` | 接进来的那一刻,这个仓库上已经有哪些议题(可选能力) |

`list_issues` 是**可选**的:不声明就是"这个来源列不出来",入口照原样说"列不了",
不去猜、不兜底。声明了就要一次返回本页的所有议题,由 `since` 给出下一页的继续点
(见 `IssuePage`)—— 分页是"这个来源怎么翻页"的事,核心不知道任何一家的游标。

**不拿某一个适配器兜底**:把 GitHub 的仓库名发给 CNB,要么 404,要么在另一个
仓库里留下一条评论。所以解析只有一种"找不到"的表达 —— `LookupError`,调用方
据此如实报错,不猜。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 一条评论要平台动起来,得有人用这些词叫它。空元组 = 这个来源不接评论触发。
DEFAULT_MENTIONS: tuple[str, ...] = ()


@dataclass(frozen=True)
class IssueRef:
    """来源上的一个议题,已经归一化成平台这一侧的形状。

    只有这几栏:`repo` / `source` 由调用方补(它才知道自己在接哪个仓库),
    `number` 每一条都必须有 —— 议题号是仓库内唯一的那个键,别的都可能缺。
    """

    number: int
    title: str
    body: str = ""
    action: str = "opened"
    is_pull: bool = False


@dataclass(frozen=True)
class IssuePage:
    """一页议题 + 下一页的继续点。

    `cursor` 为空 = 没有下一页。它是不透明的:核心只把它原样交还给同一个适配器,
    不解释、不拼装 —— 游标是"这个来源怎么翻页"的事。
    """

    issues: list[IssueRef] = field(default_factory=list)
    cursor: str = ""


async def list_issues_of(adapter: Any, repo: str, cursor: str = "") -> IssuePage:
    """问适配器要一页议题。没声明这个能力就抛 `LookupError`,由调用方如实报告。"""
    fn = getattr(adapter, "list_issues", None)
    if fn is None:
        raise LookupError(
            f"{type(adapter).__name__} 没有实现 list_issues:这个来源列不出仓库里已有的议题"
        )
    return await fn(repo, cursor)


def source_adapter(source: str) -> Any:
    """按来源名取适配器:声明了 `source` 且能收 webhook 的那一个。

    这是核心与"有哪些来源"的唯一接触面。注册表没加载、来源没装、或同名来源
    有多个提供者,一律抛 `LookupError` —— 本函数不返回 None,调用方也不必再
    判空一次"会不会拿到一个错的默认适配器"。
    """
    if not source:
        raise LookupError("没有来源名就没有适配器")
    try:
        from engine.plugin_manager import registry

        adapter = registry.webhook_adapter(source)
    except LookupError:
        raise
    except Exception as exc:  # noqa: BLE001 - 注册表没加载:当成"这个来源不可用"
        raise LookupError(f"插件注册表没起来,取不到 {source} 的适配器:{exc}") from exc
    if adapter is None:
        raise LookupError(
            f"没有为 {source} 配置 webhook 适配器:装上声明 webhook.receive 的插件再来"
        )
    return adapter


def mentions_of(adapter: Any) -> tuple[str, ...]:
    """适配器声明的触发词。没声明就是"这个来源不接评论触发",不继承别人的名字。"""
    raw = getattr(adapter, "mentions", DEFAULT_MENTIONS) or ()
    return tuple(str(item).lower() for item in raw if str(item).strip())


def mentions_prompt(adapter: Any, body: str) -> bool:
    """这条评论叫到平台了吗。大小写不敏感:人写 `@CodeBuddy` 还是 `@codebuddy` 都算。"""
    text = (body or "").lower()
    return any(term in text for term in mentions_of(adapter))


async def workspace_source_of(adapter: Any, repo: str) -> Any:
    """这个来源的"代码从哪来"。

    返回 `engine.harness.workspace.Source`。适配器没实现就是不知道怎么把代码交给
    这场运行 —— 抛 `LookupError`,工作流据此如实报告"没开工",而不是拿某个默认
    来源去拉一份不相干的代码。
    """
    fn = getattr(adapter, "workspace_source", None)
    if fn is None:
        raise LookupError(
            f"{type(adapter).__name__} 没有实现 workspace_source:这个来源的代码进不了工作区"
        )
    return await fn(repo)


__all__ = [
    "DEFAULT_MENTIONS",
    "IssuePage",
    "IssueRef",
    "list_issues_of",
    "mentions_of",
    "mentions_prompt",
    "source_adapter",
    "workspace_source_of",
]
