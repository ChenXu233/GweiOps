# engine/agent/console.py
"""控制台助手的会话、权限与审批。loop 用 bub,出口仍是 `run_tool`。

- **会话**(`ConsoleSession`):权限、资源、绑定、模型记在会话上,落库
  (`console_sessions`、`console_messages`),进程内只留缓存,便于审计回查。
- **权限**:工具清单按**此刻的调用者**算(与 `/mcp` 的 `tools/list` 同一判据
  `tool_visible`),再被会话白名单收窄。会话权限只是上限,每轮与调用者当前
  权限取交集——权限被回收或换了令牌,旧会话不能继续用。
- **审批**:会话开着 `confirm` 时,改世界的调用不直接执行,落成待批调用,
  批准后才走出口。只读能力(名字以 `.read` 结尾)不需要批准。

多步循环由 `bub.core.Agent` 提供,平台只负责出口。
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from engine.auth import ALL_PERMISSIONS, is_write_permission
from engine.auth.keys import is_scoped, permission_for_tool, tool_visible

logger = logging.getLogger(__name__)

# 一次对话最多几步模型调用。
MAX_STEPS = 8
# 一次会话最多几次改世界的调用;与租户级的出口小时上限是两回事。
MAX_ACTIONS = 6
# 等待人工批准的超时;超时后本轮结束。
APPROVAL_TIMEOUT_SECONDS = 300.0
# 会话闲置回收时限;只作用于进程内缓存。
SESSION_TTL_SECONDS = 1800.0

SYSTEM_PROMPT = """你是 GweiOps 控制台助手,在这台机器上代用户执行运维操作。

规则:
1. 只有工具能改变外部状态,每次改世界的调用都经过平台判定,可能被拒、被拦、被撤销。
   被拒时读 reason,换办法或停手,不要反复重试同一动作。
2. 拿不准先用只读工具确认。
3. 需要人工批准的操作由平台向用户发起确认;未经确认不要宣称已执行。
4. 用中文回答,句子简短:看了什么、做了什么、结果如何、还剩什么。
"""


class SessionError(ValueError):
    """会话操作被拒绝。message 面向用户。"""


@dataclass
class PendingCall:
    """一次待人工批准的改世界调用;参数保留到批准后原样执行。"""

    id: str
    name: str
    args: dict[str, Any]
    summary: str = ""
    created_at: float = field(default_factory=time.time)
    decision: str = ""  # "" 待批 / allow / deny
    reason: str = ""


@dataclass
class ToolResult:
    """回给模型的结果:ok / verdict / reason / data 原样带回。"""

    ok: bool
    verdict: str = ""
    reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok}
        if self.verdict:
            out["verdict"] = self.verdict
        if self.reason:
            out["reason"] = self.reason
        if self.data:
            out["data"] = self.data
        return out


@dataclass
class ConsoleSession:
    """一个会话;权限、资源、模型等运行时上下文。"""

    id: str
    tenant: str
    actor: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    bindings: frozenset[str] = field(default_factory=frozenset)
    # 工具白名单;空 = 按权限给全部(与密钥同口径)。
    tools: frozenset[str] = field(default_factory=frozenset)
    confirm: bool = True
    model: str = ""
    binding: str = ""
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    # 已用的改世界次数,按会话累计。
    actions: int = 0

    def touch(self) -> None:
        self.last_used_at = time.time()

    def expired(self, now: float | None = None) -> bool:
        return ((now or time.time()) - self.last_used_at) > SESSION_TTL_SECONDS

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant": self.tenant,
            "actor": self.actor,
            "permissions": sorted(self.permissions),
            "bindings": sorted(self.bindings),
            "tools": sorted(self.tools),
            "confirm": self.confirm,
            "model": self.model,
            "binding": self.binding,
            "actions": self.actions,
            "max_actions": MAX_ACTIONS,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
        }


# 进程内只做缓存:事实在 console_sessions / console_messages 两张表里。
_SESSIONS: dict[str, ConsoleSession] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sweep() -> None:
    for key in [k for k, s in _SESSIONS.items() if s.expired()]:
        _SESSIONS.pop(key, None)


def reset() -> None:
    """测试用:清空进程内的缓存。"""
    _SESSIONS.clear()


def sessions() -> dict[str, ConsoleSession]:
    _sweep()
    return _SESSIONS


async def get_session(session_id: str) -> ConsoleSession:
    """取会话;缓存未命中时从库读回。"""
    _sweep()
    found = _SESSIONS.get(session_id)
    if found is None:
        found = await _load(session_id)
        if found is None:
            raise SessionError("会话不存在:已关闭或已超时")
        _SESSIONS[found.id] = found
    found.touch()
    return found


def _held_permissions(actor: Any) -> frozenset[str]:
    """调用者当前持有的权限;会话授权不能超过它。

    静态令牌没有权限集(只有 read/operate scope),按 scope 映射,口径与 `grantable` 一致。
    """
    if actor is None:
        # 未开鉴权的部署:按 operate 记账(单机自用)。
        return frozenset(ALL_PERMISSIONS)
    if is_scoped(actor):
        return frozenset(getattr(actor, "permissions", frozenset()))
    return _scope_permissions(getattr(actor, "scope", ""))


def _scope_permissions(scope: str) -> frozenset[str]:
    """静态令牌的权限集:read 只给只读口,operate 给全部。

    read 不能映射成空集:空权限在 `tool_visible` 的静态令牌路径上会按 scope 放行,
    反而放行更多。
    """
    from engine.auth import PERMISSIONS, READ_PERMISSIONS

    if scope != "operate":
        return frozenset(READ_PERMISSIONS)
    return frozenset(PERMISSIONS)


def effective_permissions(session: ConsoleSession, actor: Any) -> frozenset[str]:
    """本轮生效的权限 = 会话权限 ∩ 调用者当前权限。

    会话只是上限:权限被回收、换了令牌,都不能继续用会话创建时的权限。
    `actor is None` 表示未开鉴权,此时只看会话本身(归属已由 `_session` 核对)。
    """
    if actor is None:
        return session.permissions
    return frozenset(session.permissions) & _held_permissions(actor)


def _check_owner(session: ConsoleSession, actor: Any) -> None:
    """核对会话归属;借到会话等于借到权限,归属不符即拒绝。"""
    name = str(getattr(actor, "name", "") or "")
    if name and session.actor and session.actor != name:
        raise SessionError("这个会话不属于当前身份")
    tenant = str(getattr(actor, "tenant", "") or "")
    if tenant and session.tenant and tenant != session.tenant:
        raise SessionError("这个会话不属于当前租户")


# ---------------------------------------------------------------------------
# 落库:会话(mutable,一行)与对话(append-only,一行一句)
# ---------------------------------------------------------------------------


async def ensure_schema() -> None:
    """建会话与对话两张表(checkfirst)。和账本、事故一样:启动时兜一次。"""
    from engine.db.engine import engine
    from engine.db.models.console_session import ConsoleMessageRow, ConsoleSessionRow

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: ConsoleSessionRow.__table__.create(c, checkfirst=True))
        await conn.run_sync(lambda c: ConsoleMessageRow.__table__.create(c, checkfirst=True))


class StorageUnavailable(RuntimeError):
    """会话持久化失败;开会话时不降级为内存会话。"""


async def persist(session: ConsoleSession) -> None:
    """把会话当前状态写回数据库;失败直接抛出,否则权限收窄会落空。"""
    from sqlalchemy import update

    from engine.db.engine import async_session_factory
    from engine.db.models.console_session import ConsoleSessionRow

    try:
        async with async_session_factory() as db:
            await db.execute(
                update(ConsoleSessionRow)
                .where(ConsoleSessionRow.id == session.id)
                .values(
                    permissions=sorted(session.permissions),
                    bindings=sorted(session.bindings),
                    tools=sorted(session.tools),
                    confirm=session.confirm,
                    actions=session.actions,
                    binding=session.binding,
                    model=session.model,
                    last_used_at=_now_iso(),
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 - 换个类型抛出去,免得路由把它当 500 的意外
        raise StorageUnavailable(f"会话未能落库:{type(exc).__name__}: {exc}") from exc


async def record(
    session: ConsoleSession,
    role: str,
    content: str = "",
    payload: dict[str, Any] | None = None,
) -> None:
    """追加一行对话记录(审计)。写失败只记日志、不打断本轮;日志带会话 id。
    """
    from engine.db.engine import async_session_factory
    from engine.db.models.console_session import ConsoleMessageRow

    try:
        async with async_session_factory() as db:
            db.add(
                ConsoleMessageRow(
                    session_id=session.id,
                    tenant=session.tenant,
                    actor=session.actor,
                    role=role,
                    content=content or "",
                    payload=payload or {},
                )
            )
            await db.commit()
    except Exception:  # noqa: BLE001 - 记日志比让这一轮断掉更有用
        logger.warning("控制台对话未能落库:session=%s role=%s", session.id, role, exc_info=True)


async def _load(session_id: str) -> ConsoleSession | None:
    from sqlalchemy import select

    from engine.db.engine import async_session_factory
    from engine.db.models.console_session import ConsoleSessionRow

    try:
        async with async_session_factory() as db:
            row = (
                await db.execute(select(ConsoleSessionRow).where(ConsoleSessionRow.id == session_id))
            ).scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001
        raise StorageUnavailable(f"会话未能读取:{type(exc).__name__}: {exc}") from exc
    if row is None:
        return None
    return ConsoleSession(
        id=row.id,
        tenant=row.tenant,
        actor=row.actor,
        permissions=frozenset(row.permissions or ()),
        bindings=frozenset(row.bindings or ()),
        tools=frozenset(row.tools or ()),
        confirm=bool(row.confirm),
        model=row.model,
        binding=row.binding,
        actions=int(row.actions or 0),
        created_at=_parse_ts(row.created_at),
        last_used_at=_parse_ts(row.last_used_at),
    )


def _parse_ts(raw: str) -> float:
    try:
        return datetime.fromisoformat(raw).timestamp()
    except (TypeError, ValueError):
        return time.time()


async def history(session_id: str, limit: int = 200) -> list[dict[str, Any]]:
    """会话的对话记录,按写入顺序。"""
    from sqlalchemy import select

    from engine.db.engine import async_session_factory
    from engine.db.models.console_session import ConsoleMessageRow

    async with async_session_factory() as db:
        rows = (
            (
                await db.execute(
                    select(ConsoleMessageRow)
                    .where(ConsoleMessageRow.session_id == session_id)
                    .order_by(ConsoleMessageRow.id)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    return [
        {
            "id": row.id,
            "role": row.role,
            "content": row.content,
            "payload": row.payload or {},
            "created_at": row.created_at,
        }
        for row in rows
    ]


def _refuse_overreach(wanted: set[str], granted: frozenset[str], what: str) -> None:
    over = sorted(wanted - granted)
    if over:
        raise SessionError(f"不能授予当前身份没有的{what}:{', '.join(over)}")


async def open_session(
    *,
    actor: Any,
    tenant: str,
    binding: str = "",
    permissions: list[str] | None = None,
    bindings: list[str] | None = None,
    tools: list[str] | None = None,
    confirm: bool = True,
    model: str = "",
    storage: bool = True,
) -> ConsoleSession:
    """开一个新会话,默认授予该身份的全部权限(只能收窄)。

    `storage=False` 仅用于测试;默认落库,不落库的会话没有审计依据。
    """
    held = _held_permissions(actor)
    # 不填 = 按身份可给的全部;填了则核对,会话只能收窄。
    granted = frozenset(permissions) if permissions is not None else held
    unknown = set(granted) - ALL_PERMISSIONS
    if unknown:
        raise SessionError(f"没有这些权限:{', '.join(sorted(unknown))}")
    _refuse_overreach(set(granted), held, "权限")

    allowed_bindings = frozenset(bindings) if bindings is not None else frozenset(
        getattr(actor, "bindings", frozenset())
    )
    known_bindings = frozenset(getattr(actor, "bindings", frozenset()))
    if known_bindings:
        # 身份只在一部分资源上有效时,会话不能替它扩出来
        _refuse_overreach(set(allowed_bindings), known_bindings, "资源")

    session = ConsoleSession(
        id=secrets.token_urlsafe(12),
        tenant=tenant or "",
        actor=str(getattr(actor, "name", "") or ""),
        permissions=granted,
        bindings=allowed_bindings,
        tools=frozenset(tools or ()),
        confirm=bool(confirm),
        model=model or "",
        binding=binding or "",
    )
    if storage:
        await _insert(session)
    _SESSIONS[session.id] = session
    if storage:
        await _audit(
            session, "session.open", {"permissions": sorted(granted), "confirm": session.confirm}
        )
    return session


async def _insert(session: ConsoleSession) -> None:
    """插入会话行;失败即报错,不返回会话。"""
    from engine.db.engine import async_session_factory
    from engine.db.models.console_session import ConsoleSessionRow

    try:
        async with async_session_factory() as db:
            db.add(
                ConsoleSessionRow(
                    id=session.id,
                    tenant=session.tenant,
                    actor=session.actor,
                    binding=session.binding,
                    model=session.model,
                    permissions=sorted(session.permissions),
                    bindings=sorted(session.bindings),
                    tools=sorted(session.tools),
                    confirm=session.confirm,
                    actions=session.actions,
                    created_at=_now_iso(),
                    last_used_at=_now_iso(),
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        raise StorageUnavailable(f"会话未能落库:{type(exc).__name__}: {exc}") from exc


async def _audit(session: ConsoleSession, action: str, detail: dict[str, Any] | None = None) -> None:
    """会话级变更(开、改、关)的审计,与对话记录分开。"""
    await record(session, "session", action, {"action": action, **(detail or {})})


async def update_session(
    session: ConsoleSession,
    *,
    actor: Any = None,
    permissions: list[str] | None = None,
    tools: list[str] | None = None,
    bindings: list[str] | None = None,
    confirm: bool | None = None,
) -> ConsoleSession:
    """修改会话;授权上限与开会话一致。"""
    if permissions is not None:
        wanted = frozenset(permissions)
        _refuse_overreach(set(wanted), _held_permissions(actor), "权限")
        session.permissions = wanted
    if tools is not None:
        session.tools = frozenset(tools)
    if bindings is not None:
        session.bindings = frozenset(bindings)
    if confirm is not None:
        session.confirm = bool(confirm)
    session.touch()
    await persist(session)
    await _audit(
        session,
        "session.update",
        {
            "permissions": sorted(session.permissions),
            "tools": sorted(session.tools),
            "confirm": session.confirm,
        },
    )
    return session


async def close_session(session_id: str) -> bool:
    found = _SESSIONS.pop(session_id, None)
    if found is None:
        found = await _load(session_id)
    if found is None:
        return False
    await _audit(found, "session.close", {})
    from sqlalchemy import delete

    from engine.db.engine import async_session_factory
    from engine.db.models.console_session import ConsoleSessionRow

    async with async_session_factory() as db:
        await db.execute(delete(ConsoleSessionRow).where(ConsoleSessionRow.id == session_id))
        await db.commit()
    return True


# ---------------------------------------------------------------------------
# 权限:一个工具在这个会话里能不能用
# ---------------------------------------------------------------------------


def session_allows(
    session: ConsoleSession, tool: str, bindings_of: Any = None, actor: Any = None
) -> bool:
    """会话能否使用这个工具。

    判据在 `tool_visible`(权限、白名单、资源),会话白名单再收窄一层,不另写权限表。
    权限按**此刻的调用者**取交集(`effective_permissions`):否则权限被收回后,
    未过期的会话仍能用旧工具集,形成静默提权。
    """
    from engine.api.auth import Actor

    granted = effective_permissions(session, actor)
    proxy = Actor(
        token_id="console",
        name=session.actor,
        tenant=session.tenant,
        scope="operate" if any(is_write_permission(p) for p in granted) else "read",
        permissions=granted,
        bindings=session.bindings,
    )
    visible = tool_visible(tool, actor or proxy, bindings_of) if actor is not None else tool_visible(
        tool, proxy, bindings_of
    )
    if not visible:
        return False
    if session.tools and tool not in session.tools:
        return False
    # 工具所需权限须落在生效权限集里:`tool_visible` 收窄用的身份可能带静态 scope,
    # 这里只认 `granted`。
    return permission_for_tool(tool) in granted


def describe_tools(
    session: ConsoleSession, registry: Any, actor: Any = None
) -> list[dict[str, Any]]:
    """会话看到的工具清单。与 `/mcp` 的 `tools/list` 同一份事实来源:出口清单。"""
    from engine.agent.tools import tool_specs

    out: list[dict[str, Any]] = []
    for spec in tool_specs(registry):
        function = spec.get("function") or {}
        name = str(function.get("name") or "")
        if not name or not session_allows(
            session, name, getattr(registry, "tool_bindings", None), actor
        ):
            continue
        out.append(
            {
                "name": name,
                "description": str(function.get("description") or name),
                "parameters": function.get("parameters") or {"type": "object", "properties": {}},
                "permission": permission_for_tool(name),
                "mutating": name in registry.declared_effects(),
            }
        )
    return out


def model_tool_name(capability: str) -> str:
    """模型看到的工具名:`.` 换成 `_`(部分函数调用格式不接受带点的名字)。
    反向映射见 `capability_of`。
    """
    return capability.replace(".", "_")


def bub_tools(session: ConsoleSession, registry: Any, actor: Any = None) -> list[Any]:
    """把会话的工具清单转成 bub 的 `Tool`。参数 schema 沿用出口清单,不另编;
    `additionalProperties` 打开(出口清单未限定参数集)。清单按 `actor` 当前权限算。
    """
    from bub.core.tools import Tool

    out: list[Tool] = []
    for spec in describe_tools(session, registry, actor):
        name = model_tool_name(str(spec["name"]))
        parameters = dict(spec["parameters"] or {"type": "object", "properties": {}})
        parameters.setdefault("type", "object")
        parameters["additionalProperties"] = True
        out.append(
            Tool(
                name=name,
                handler=_make_handler(session, registry, name, actor),
                description=str(spec["description"]),
                parameters=parameters,
            )
        )
    return out


def _make_handler(session: ConsoleSession, registry: Any, model_name: str, actor: Any = None):
    capability = capability_of(model_name)

    async def handler(**kwargs: Any) -> dict[str, Any]:
        return await call_tool(session, registry, capability, kwargs, actor=actor)

    return handler


def capability_of(model_name: str) -> str:
    """模型工具名 → 能力名(`model_tool_name` 的反向)。"""
    for capability in _registry().declared_effects():
        if model_tool_name(capability) == model_name:
            return capability
    for name in getattr(_registry(), "names", lambda: [])():
        manifest = _registry().manifest(name)
        for capability in getattr(manifest, "capabilities", []) or []:
            if model_tool_name(capability) == model_name:
                return capability
    return model_name


async def call_tool(
    session: ConsoleSession,
    registry: Any,
    name: str,
    args: dict[str, Any],
    actor: Any = None,
) -> dict[str, Any]:
    """执行一次工具调用:只读直接执行,改世界的先经人工批准(如开启 confirm)。

    拒绝、超时、超限都作为**结论**返回给模型,不抛异常,避免中断本轮对话。
    """
    from engine.agent.tools import ToolCall, run_tool
    from engine.change_unit import create_ledger

    args = dict(args or {})
    await record(session, "tool_call", name, {"args": _public_args(args)})
    if not session_allows(session, name, getattr(registry, "tool_bindings", None), actor):
        result = ToolResult(
            False,
            reason=f"权限不足:{permission_for_tool(name)}(会话权限或当前身份的资源绑定不满足)",
        ).to_dict()
        await record(session, "tool_result", name, result)
        return result

    effects = registry.declared_effects()
    mutating = name in effects

    if mutating and session.confirm:
        return await ask(session, name, args, actor=actor)

    if mutating:
        if session.actions >= MAX_ACTIONS:
            result = ToolResult(
                False, reason=f"已达本次对话的改动上限({MAX_ACTIONS}),需人工处理"
            ).to_dict()
            await record(session, "tool_result", name, result)
            return result
        session.actions += 1

    result = await run_tool(
        ToolCall(name, args),
        registry=registry,
        ledger=create_ledger(),
        tenant=session.tenant,
        binding=session.binding,
        summary=args.get("_summary") or f"控制台助手调用 {name}",
        actor=session.actor,
    )
    out = result.to_dict()
    await record(session, "tool_result", name, {"args": _public_args(args), **out})
    if mutating:
        await persist(session)
    return out


def _public_args(args: dict[str, Any]) -> dict[str, Any]:
    """审计里不留内部关键字(`_summary` 这类由平台补的)。"""
    return {k: v for k, v in (args or {}).items() if not str(k).startswith("_")}


# ---------------------------------------------------------------------------
# 允许:一次改世界的调用在等人点
# ---------------------------------------------------------------------------

_PENDING: dict[str, tuple[ConsoleSession, PendingCall]] = {}


def pending_of(session: ConsoleSession) -> PendingCall | None:
    """会话当前待批的调用;同一时间只保留一件。"""
    for owner, call in _PENDING.values():
        if owner is session and not call.decision:
            return call
    return None


async def ask(
    session: ConsoleSession, name: str, args: dict[str, Any], actor: Any = None
) -> dict[str, Any]:
    """挂起这次调用等待人工批准;一个会话同时只等一件。

    批准后重新校验权限:等待期间权限可能已被收回。
    """
    import asyncio

    if pending_of(session) is not None:
        return ToolResult(False, reason="已有待批准的调用未处理").to_dict()

    call = PendingCall(
        id=secrets.token_urlsafe(8),
        name=name,
        args=args,
        summary=str(args.get("_summary") or ""),
    )
    _PENDING[call.id] = (session, call)
    try:
        deadline = time.monotonic() + APPROVAL_TIMEOUT_SECONDS
        while not call.decision and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
    finally:
        _PENDING.pop(call.id, None)

    if not call.decision:
        await record(session, "denied", name, {"reason": "approval_timeout"})
        return ToolResult(False, reason="审批超时:未在限期内点允许,本次调用未执行").to_dict()
    if call.decision == "deny":
        await record(session, "denied", name, {"reason": call.reason or "operator_denied"})
        return ToolResult(False, reason=call.reason or "审批被拒绝:本次调用未执行").to_dict()

    from engine.agent.tools import ToolCall, run_tool
    from engine.change_unit import create_ledger

    registry = _registry()
    if not session_allows(session, name, getattr(registry, "tool_bindings", None), actor):
        result = ToolResult(
            False, reason=f"权限已变更:{permission_for_tool(name)} 在等待审批期间不再有效,本次调用未执行"
        ).to_dict()
        await record(session, "tool_result", name, result)
        return result

    if session.actions >= MAX_ACTIONS:
        result = ToolResult(
            False, reason=f"已达本次对话的改动上限({MAX_ACTIONS}),需人工处理"
        ).to_dict()
        await record(session, "tool_result", name, result)
        return result
    session.actions += 1
    result = await run_tool(
        ToolCall(name, args),
        registry=registry,
        ledger=create_ledger(),
        tenant=session.tenant,
        binding=session.binding,
        summary=call.summary or f"控制台助手调用 {name}",
        actor=session.actor,
    )
    out = result.to_dict()
    await record(session, "tool_result", name, {"approved_by": session.actor, **out})
    await persist(session)
    return out


def _registry() -> Any:
    from engine.plugin_manager import registry

    return registry


async def decide(
    session: ConsoleSession, call_id: str, allow: bool, reason: str = "", actor: Any = None
) -> PendingCall:
    """记录人工决定。校验:该调用确实在等待,且决定者当前仍持有对应工具的权限。

    后者不可省:批准即授权,权限已失效时批准会把旧权限延长到执行,形成静默提权。
    """
    found = _PENDING.get(call_id)
    if found is None or found[0] is not session:
        raise SessionError("审批请求不存在:已超时、已处理,或不属于当前会话")
    call = found[1]
    if call.decision:
        raise SessionError("审批请求已处理")
    if allow and not session_allows(
        session, call.name, getattr(_registry(), "tool_bindings", None), actor
    ):
        raise SessionError(
            f"权限不足:{permission_for_tool(call.name)} 当前无效,不能批准这次调用"
        )
    call.decision = "allow" if allow else "deny"
    call.reason = reason
    return call


def describe_pending(call: PendingCall | None) -> dict[str, Any] | None:
    if call is None:
        return None
    return {
        "id": call.id,
        "name": call.name,
        "args": {k: v for k, v in call.args.items() if not str(k).startswith("_")},
        "summary": call.summary,
    }


def reset_pending() -> None:
    _PENDING.clear()

__all__ = [
    "APPROVAL_TIMEOUT_SECONDS",
    "ConsoleSession",
    "MAX_ACTIONS",
    "MAX_STEPS",
    "PendingCall",
    "SYSTEM_PROMPT",
    "SessionError",
    "StorageUnavailable",
    "ToolResult",
    "ask",
    "bub_tools",
    "call_tool",
    "close_session",
    "decide",
    "describe_pending",
    "describe_tools",
    "effective_permissions",
    "ensure_schema",
    "get_session",
    "history",
    "persist",
    "record",
    "open_session",
    "pending_of",
    "reset",
    "reset_pending",
    "session_allows",
    "sessions",
    "update_session",
]
