# engine/agent/console.py
"""控制台里的那个悬浮窗 agent —— loop 用 bub,出口还是出口。

三件事在这里定死,别处不再判第二遍:

- **会话**:一次对话是一个会话语义对象(`ConsoleSession`),权限、资源、绑定、模型
  都记在它身上。落库(`console_sessions`、`console_messages`),进程内只留一层
  缓存 —— 权限依据与每一句都要能回查,否则这个入口没有审计。
- **权限**:能调哪些工具由**此刻的调用者**算(与 `/mcp` 的 `tools/list` 同一条判据
  `tool_visible`),再被会话自己的白名单收窄一层。会话不是一次性的签名:每一轮
  都按当下这个人的权限重算一遍,会话上留着的权限只做上限 —— 人的权限被回收、
  凭据换了人,都不能靠一个还没过期的会话继续用。
- **允许**:会话开了 `confirm`,改世界的调用不直接执行,落成一条待批的调用;
  人点了允许才走出口。只读口(名字以 `.read` 结尾的能力)不受这条约束 ——
  看一眼不需要批准,也就不用把人也拉过来点一下。

loop 不自己写:推一版、看一眼、改主意的循环交给 `bub.core.Agent`,它带工具执行、
多步、事件流。平台这一侧只剩"出口"这一件事,和沙箱里那个 agent 完全相同。
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

# 一次对话最多几步模型调用。够它看两眼看一步再收尾,又不把账单跑飞。
MAX_STEPS = 8
# 一次运行最多几次改世界的调用。与出口的小时上限不是一回事:那是租户级的,这是会话语级。
MAX_ACTIONS = 6
# 等待人点"允许"的上限。人没在屏幕前,这一轮就收在这里,不挂着连接等到天荒地老。
APPROVAL_TIMEOUT_SECONDS = 300.0
# 会话闲置多久回收。只在进程内,不落库,所以这是一句内存约定。
SESSION_TTL_SECONDS = 1800.0

SYSTEM_PROMPT = """你是 GweiOps 控制台里的值班助手。用户在运维这台机器,你替他做事。

规则:
1. 只有工具能改变外部世界。每次改世界的调用都会经过平台判定:可能被拒、被拦、被撤销。
   被拒不是错误,是结论;读 reason,换办法或者停手,同一个动作不要反复试。
2. 拿不准就先看。只读工具不要钱,猜要。
3. 需要人点的动作,平台会替你把话问到用户面前。不要自己宣称已经执行。
4. 回答用中文,短句。说清楚:看了什么、做了什么、结果如何、还剩什么。
"""


class SessionError(ValueError):
    """会话操作被规则拒绝。message 直接给人看。"""


@dataclass
class PendingCall:
    """一次等人点的改世界调用。参数原样留着 —— 允许之后要照着它执行。"""

    id: str
    name: str
    args: dict[str, Any]
    summary: str = ""
    created_at: float = field(default_factory=time.time)
    decision: str = ""  # "" 待批 / allow / deny
    reason: str = ""


@dataclass
class ToolResult:
    """回给模型的结果。必须能读懂,所以 ok / verdict / reason 原样带回去。"""

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
    """一次对话。权限、资源、模型都记在这,运行时不从请求里再读一遍。"""

    id: str
    tenant: str
    actor: str
    permissions: frozenset[str] = field(default_factory=frozenset)
    bindings: frozenset[str] = field(default_factory=frozenset)
    # 白名单:会话只允许够哪些工具。空 = 按权限给全部(与密钥那一栏同一口径)。
    tools: frozenset[str] = field(default_factory=frozenset)
    confirm: bool = True
    model: str = ""
    binding: str = ""
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    # 已用掉的改世界次数。按会话累计,不按运行 —— 一次对话的总账。
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
    """取会话。缓存里没有就从库里读回来 —— 进程重启不该让一段对话连依据一起消失。"""
    _sweep()
    found = _SESSIONS.get(session_id)
    if found is None:
        found = await _load(session_id)
        if found is None:
            raise SessionError("会话不存在:已关闭,或闲置超过 SESSION_TTL_SECONDS 被回收")
        _SESSIONS[found.id] = found
    found.touch()
    return found


def _held_permissions(actor: Any) -> frozenset[str]:
    """这个人此刻手上有哪些权限。会话能给出去的,不会超过这一份。

    静态令牌没有权限集(只有 read/operate),它对"能签什么"的回答是全部或没有。
    这一条与 `grantable` 的口径一致,免得同一个部署里两种说法。
    """
    if actor is None:
        # 没配凭据的部署:没有"人"可以比对。会话按 operate 记账(单机自用)。
        return frozenset(ALL_PERMISSIONS)
    if is_scoped(actor):
        return frozenset(getattr(actor, "permissions", frozenset()))
    return _scope_permissions(getattr(actor, "scope", ""))


def _scope_permissions(scope: str) -> frozenset[str]:
    """静态令牌:read 只剩只读口,operate 是全部。

    以前这里把 read 一律算成空集 —— 于是「会话的权限」对一个只读令牌是空的,
    会话带着空权限去判 `tool_visible`,静态令牌那条"权限为空就按 scope 放行"的
    旧路径会因此放行更多。宁可少给:read 就只给只读口。
    """
    from engine.auth import PERMISSIONS, READ_PERMISSIONS

    if scope != "operate":
        return frozenset(READ_PERMISSIONS)
    return frozenset(PERMISSIONS)


def effective_permissions(session: ConsoleSession, actor: Any) -> frozenset[str]:
    """这一轮真正生效的权限 = 会话留着的 ∩ 调用者此刻手上的。

    会话只是上限,不是签名:人的权限被回收、换了令牌调用同一个会话,都不该
    继续拿到会话创建时的权限。`actor is None` 表示这个部署没开鉴权,没有可比对
    的人,于是只看会话自己(`_session` 已经核对过归属)。
    """
    if actor is None:
        return session.permissions
    return frozenset(session.permissions) & _held_permissions(actor)


def _check_owner(session: ConsoleSession, actor: Any) -> None:
    """会话属于这个身份吗。归属不对就是 403 —— 借一个会话等于借它的权限。"""
    name = str(getattr(actor, "name", "") or "")
    if name and session.actor and session.actor != name:
        raise SessionError("这个会话不属于当前身份")
    tenant = str(getattr(actor, "tenant", "") or "")
    if tenant and session.tenant and tenant != session.tenant:
        raise SessionError("这个会话不属于当前租户")


# ---------------------------------------------------------------------------
# 落库:会话(mutable,一行)与对话(append-only,一行一句)
# ---------------------------------------------------------------------------


class StorageUnavailable(RuntimeError):
    """会话存不下来。开会话时这必须是错误,不能退化成"只在内存里活着"。"""


async def persist(session: ConsoleSession) -> None:
    """把会话当前的样子写回去。失败就是失败 —— 权限改窄了却没落库,下次读回来是旧的。"""
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
    """追加一行对话。审计靠它:说了什么、调了什么、结果是拒还是被允许。

    写不进去时只记日志、不打断这一轮 —— 对话仍在继续,但库里的审计会缺一段,
    所以这一条在 WARNING 里带上会话 id。
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
    """这一段对话的行,按写入顺序。审计与"界面重开还能看到"共用这一份。"""
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
        raise SessionError(f"你手上没有这些{what},给不出去:{', '.join(over)}")


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
) -> ConsoleSession:
    """开一个新会话。默认给到这个身份的全部 —— 只有它自己能收窄自己。"""
    held = _held_permissions(actor)
    # 不填 = 按这个人能给的来。填了就核对一遍:会话只能越用越窄。
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
    await _insert(session)
    _SESSIONS[session.id] = session
    await _audit(session, "session.open", {"permissions": sorted(granted), "confirm": session.confirm})
    return session


async def _insert(session: ConsoleSession) -> None:
    """建一行。写不进去就别返回这个会话 —— 一个只在内存里的会话没有审计依据。"""
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
    """会话本身的变更(开、改、关)。与对话分开记,免得"谁把权限改窄了"埋在对话里。"""
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
    """改会话。能给的只有这个人手上有的 —— 改的时候与开的时候同一条红线。"""
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
    """这个会话够不够得着这个工具。

    判据全在 `tool_visible`:权限集、身份自带的白名单、资源三关。会话再收窄一层。
    这里不重写一遍权限表 —— 第二份判据迟早与第一份打架。

    **权限按此刻的调用者现算**,不是会话创建时的那一份:`effective_permissions`
    取会话权限与这个人当下权限的交集。少了这一步,一个人被收回权限之后,他手上
    还没过期的会话仍能拿到原来的工具集 —— 那就是静默提权。
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
    # 最后一道:这个工具要的权限得在这次生效的权限集里。`tool_visible` 已经判过一遍,
    # 这里再落一次是因为它收窄用的身份可能带 static 态;权限判据只认 `granted`。
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
    """能力名交给模型时的样子。

    `.` 换成 `_`:同一个名字要走通好几家的函数调用格式,而 `compose.scale` 这种
    带点的名字在中间被改写是常态(bub 自己也会换)。换回来的映射只此一处。
    """
    return capability.replace(".", "_")


def bub_tools(session: ConsoleSession, registry: Any, actor: Any = None) -> list[Any]:
    """把会话的工具清单翻成 bub 的 `Tool`。

    参数 schema 直接用出口清单给的那份 —— 参数名来自插件声明,不是这里编的。
    `additionalProperties` 打开:出口清单只说了"有这些参数",没说"只能有这些"。
    `actor` 是这一轮的调用者:清单按他当下的权限算。
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
    """模型给的名字 → 能力名。清单里的每一个都由 `model_tool_name` 换过一次,这里换回来。"""
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
    """一次工具调用。只读直接做,改世界的要人点允许。

    人点拒绝、超时、次数用完都是**结论**,不是异常:它们原样回到模型手里,
    模型据此换办法或者收尾。抛出只会让这轮对话断在半路。
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
                False, reason=f"这次对话已经改了 {session.actions} 次,到上限 {MAX_ACTIONS} 了;停手,由人接手"
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
    """这个会话正在等的那一次。一次只等一件:排队批的东西人看不明白。"""
    for owner, call in _PENDING.values():
        if owner is session and not call.decision:
            return call
    return None


async def ask(
    session: ConsoleSession, name: str, args: dict[str, Any], actor: Any = None
) -> dict[str, Any]:
    """把这次调用摆到人面前,等到他点。

    这里等的是**人**,不是锁:同一个人可以有多个会话,但一个会话只有一次在等。

    批准之后再判一次权限:等人点的这段时间里,人的权限可能已经被收回。
    """
    import asyncio

    if pending_of(session) is not None:
        return ToolResult(False, reason="上一个批准请求仍在等待,先处理它").to_dict()

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
            False, reason=f"这次对话已经改了 {session.actions} 次,到上限 {MAX_ACTIONS} 了;停手,由人接手"
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
    """人点了。判据:这个会话确实有这么一次在等,并且点的人此刻仍然拿得到这个工具。

    后一条不是多余的:批准这一步本身就是一次授权,如果那时权限已经没了,
    点一下就把旧权限延长到了执行 —— 静默提权最常见的形状。
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
