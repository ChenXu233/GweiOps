# plugins/builtin/adapters/cnb/plugin.py
"""CNB(cnb.cool)适配器 —— 托管源之一。

CNB 的事件形状(`PullRequestEvent` / 评论投递)留在这一层,核心只收到归一化的
`kind`。回评、开 PR、取快照也在这里:核心不认识 CNB 的地址,也不认识它的令牌。

托管源与 NPC 管道的分界写在 `engine/ingest/source.py`:这一层只管"投递怎么说、
代码从哪来、话往哪回",谁在沙箱里干活是 harness 的事。
"""

from __future__ import annotations

import hmac
import json
from typing import Any, Dict

from engine.change_unit import EffectNotApplied
from engine.harness.workspace import Source as WorkspaceSource
from engine.ingest.events import EventError, event as normalized_event, header_value
from engine.plugin_manager.base import PluginBase, PluginInfo, PluginType

from .client import CNBClient, CNBError
from .config import CNBConfig

SOURCE = "cnb"

# CNB 上人叫平台用的名字。NPC 角色在 CNB 上叫 `@<角色名>`,不是 GitHub 那个 `@gwei`。
DEFAULT_MENTIONS = ("@gwei", "@codebuddy")

TASKS = {"comment.create": "create_comment", "pr.open": "open_pull"}


class CNBAdapter(PluginBase):
    def __init__(self) -> None:
        self.config: CNBConfig | None = None
        self.client: CNBClient | None = None
        self.binding = "cnb"
        self.tenant = ""
        self.source = SOURCE
        # 触发词由来源自己定:核心不认识 `@gwei` 这个名字。
        self.mentions = DEFAULT_MENTIONS
        # 没配密钥时,入口按这个名字告诉人该去填什么(核心不维护来源清单)。
        self.config_hint = "CNB_WEBHOOK_TOKEN"

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="cnb-adapter",
            version="0.2.0",
            type=PluginType.ADAPTER,
            description="CNB(cnb.cool)适配器:议题/评论/合并事件,回评与开 PR,仓库快照",
            capabilities=[
                "webhook.receive",
                "webhook.verify",
                "comment.create",
                "pr.open",
            ],
            config={
                "required": ["CNB_WEBHOOK_TOKEN"],
                "optional": [
                    "CNB_BASE_URL",
                    "CNB_WEB_BASE_URL",
                    "CNB_TOKEN",
                    "CNB_WEBHOOK_HEADER",
                ],
            },
        )

    async def on_startup(self) -> None:
        self.config = CNBConfig()
        self.client = CNBClient(self.config) if self.config.token else None

    async def on_shutdown(self) -> None:
        self.config = None
        self.client = None

    async def health_check(self) -> bool:
        return self.config is not None

    async def handle_event(self, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "ignored", "event": event}

    async def execute_task(self, task: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "error", "message": f"Unknown task: {task}"}

    # -- Webhook:验签与归一化 --------------------------------------

    def webhook_configured(self) -> bool:
        return bool(self.config and self.config.webhook_token)

    def verify_webhook(self, headers: Dict[str, Any], body: bytes) -> bool:
        if not self.webhook_configured():
            return False
        sent = header_value(headers, self.config.webhook_header)
        return bool(sent) and hmac.compare_digest(sent, self.config.webhook_token)

    def parse_webhook(self, headers: Dict[str, Any], body: bytes) -> Dict[str, Any] | None:
        try:
            payload = json.loads(body)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return normalize_event(payload)
        except EventError:
            return None

    # -- 读:这个编号的合并请求是什么 -------------------------------

    async def read_pull(self, repo: str, number: int) -> Dict[str, Any] | None:
        client = self._client()
        pull = await client.get_pull(repo, number)
        if pull is None:
            return None
        head = pull.get("head") or {}
        return {
            "url": pull.get("html_url") or pull.get("url") or "",
            "state": pull.get("state") or "",
            "head": {"ref": head.get("ref") or pull.get("head_ref") or ""},
        }

    # -- 工作区:代码从哪来 -----------------------------------------

    async def workspace_source(self, repo: str) -> WorkspaceSource:
        """CNB 的仓库快照。基线是仓库默认分支 —— 这一场要改的是主干。"""
        client = self._client()
        branch = await client.default_branch(repo)
        if not branch:
            raise RuntimeError(f"取不到 {repo} 的默认分支:工作区不知道该落在哪个基线上")
        return WorkspaceSource(
            archive_url=await client.archive_url(repo, branch),
            token=self.config.token,
            branch=branch,
        )

    # -- 变更单元:效果提供者 --------------------------------------

    async def execute(self, task: str, args: Dict[str, Any]) -> Dict[str, Any]:
        client = self._client()
        if task == "create_comment":
            try:
                result = await client.create_comment(
                    args["repo"],
                    int(args["issue_number"]),
                    args["body"],
                    is_pull=bool(args.get("is_pull")),
                )
            except CNBError as exc:
                if exc.not_applied:
                    raise EffectNotApplied(str(exc)) from exc
                raise
            return {
                "handle": str(result.get("id") or result.get("comment_id") or ""),
                "url": result.get("html_url") or result.get("url") or "",
            }

        if task == "open_pull":
            return await self._open_pull(client, args)

        raise EffectNotApplied(f"不认识的 CNB 效果:{task}")

    async def undo(self, task: str, args: Dict[str, Any], handle: str) -> Dict[str, Any]:
        client = self._client()
        if task == "delete_comment":
            await client.delete_comment(
                args["repo"], int(handle), is_pull=bool(args.get("is_pull"))
            )
            return {"deleted": handle}
        if task == "close_pull":
            await client.close_pull(args["repo"], int(handle))
            return {"closed": handle}
        return {"undone": handle}

    async def _open_pull(self, client: CNBClient, args: Dict[str, Any]) -> Dict[str, Any]:
        """分支 → 提交 → 合并请求。

        CNB 的一条内容改动由 `cnb` 流水线里的 git 提交,平台这一步只负责"把分支
        变成可审的合并请求"。缺参数、没配令牌都是"什么都没发生",记可重试的 failed。
        """
        missing = [name for name in ("repo", "head") if not str(args.get(name) or "").strip()]
        if missing:
            raise EffectNotApplied(f"开 PR 缺参数:{'、'.join(missing)}")
        base = str(args.get("base") or "") or await client.default_branch(args["repo"])
        if not base:
            raise RuntimeError(f"取不到 {args['repo']} 的默认分支,开 PR 需要知道基线")
        pull = await client.create_pull(
            args["repo"],
            head=args["head"],
            base=base,
            title=args.get("title") or args["head"],
            body=args.get("body") or "",
        )
        return {
            "handle": str(pull.get("number") or ""),
            "url": pull.get("html_url") or pull.get("url") or "",
            "branch": args["head"],
            "base": base,
        }

    def _client(self) -> CNBClient:
        if self.client is None:
            if self.config is None:
                self.config = CNBConfig()
            self.client = CNBClient(self.config)
        return self.client


def _repo_of(payload: dict[str, Any]) -> tuple[str, Any]:
    repo_raw = payload.get("repo") or {}
    return str(repo_raw.get("path") or repo_raw.get("full_name") or ""), repo_raw.get("id")


def normalize_event(payload: dict[str, Any]) -> dict[str, Any] | None:
    """CNB 投递 → 归一化事件;认不出来的返回 None。

    CNB 的三种投递(合并、议题、评论)字段名各不相同,都在这里翻译一次。
    """
    kind = payload.get("type") or payload.get("event") or ""
    if kind == "PullRequestEvent":
        return normalize_pull_request_event(payload)
    if kind in ("IssueEvent", "IssueCommentEvent", "NoteEvent"):
        return normalize_issue_event(payload, kind)
    return None


def normalize_issue_event(payload: dict[str, Any], kind: str) -> dict[str, Any] | None:
    """CNB 的议题与评论投递。

    - `IssueEvent`: 议题本身被开、被编辑 → `kind="issue"`
    - `IssueCommentEvent` / `NoteEvent`: 有人在议题或 PR 下说话 → `kind="comment"`
    """
    action = str(payload.get("action") or "")
    repo, repo_id = _repo_of(payload)
    if not repo:
        return None

    issue = payload.get("issue") or {}
    comment = payload.get("comment") or payload.get("note") or {}
    pull = payload.get("pull_request") or {}
    # PR 上的评论走 PR 那套字段;议题上的走 issue。
    body_holder = pull or issue
    number = body_holder.get("number") or body_holder.get("iid") or payload.get("number")
    if number is None:
        return None
    is_pull = bool(pull)

    if kind == "IssueEvent":
        if action not in ("opened", "edited", "reopened", ""):
            return None
        return normalized_event(
            kind="issue",
            source=SOURCE,
            repo=repo,
            repo_id=repo_id,
            change_id=issue.get("id") or payload.get("id"),
            number=number,
            title=issue.get("title") or "",
            body=issue.get("body") or issue.get("description") or "",
            action=action or "opened",
            is_pull=is_pull,
            url=body_holder.get("html_url") or body_holder.get("url") or "",
            sender=((payload.get("sender") or payload.get("actor") or {}).get("username") or ""),
        )

    if action and action not in ("created", "edited"):
        return None
    return normalized_event(
        kind="comment",
        source=SOURCE,
        repo=repo,
        repo_id=repo_id,
        change_id=body_holder.get("id") or payload.get("id"),
        number=number,
        title=body_holder.get("title") or "",
        body=comment.get("body") or "",
        action=action or "created",
        is_pull=is_pull,
        url=comment.get("html_url") or comment.get("url") or "",
        sender=((payload.get("sender") or payload.get("actor") or {}).get("username") or ""),
    )


def normalize_pull_request_event(payload: dict[str, Any]) -> dict[str, Any] | None:
    """CNB PullRequestEvent → 归一化事件;不是合并就返回 None。"""
    if payload.get("action") != "closed":
        return None

    pull = payload.get("pull_request") or {}
    merged = (
        bool(pull.get("merged"))
        or str(pull.get("state") or "") == "merged"
        or bool(pull.get("merged_at"))
    )
    if not merged:
        return None

    repo, repo_id = _repo_of(payload)
    if not repo:
        return None

    base = pull.get("base") or {}
    head = pull.get("head") or {}
    # CNB 的 PullRequestEvent 不总是带 merge_commit_sha;没有就交给发布侧
    # 如实报告"缺少合并提交",不拿 head 的分支名冒充。
    merge_sha = str(pull.get("merge_commit_sha") or payload.get("merge_commit_sha") or "")
    return normalized_event(
        kind="merge",
        source=SOURCE,
        repo=repo,
        repo_id=repo_id,
        change_id=pull.get("id") or payload.get("id"),
        number=pull.get("number") or payload.get("number"),
        title=pull.get("title") or "",
        body=pull.get("body") or "",
        action="merged",
        base_ref=base.get("ref") or "",
        head_ref=head.get("ref") or "",
        merge_sha=merge_sha,
        url=pull.get("html_url") or "",
        sender=((payload.get("actor") or {}).get("username") or ""),
    )
