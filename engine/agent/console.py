# engine/agent/console.py
"""控制台里的那个悬浮窗 agent —— loop 用 bub,出口还是出口。

三件事在这里定死,别处不再判第二遍:

- **会话**:一次对话是一个会话语义对象(`ConsoleSession`),权限、资源、绑定、模型
  都记在它身上。进程内内存,引擎重启就散 —— 对话不是账本,值不值得留由人来定,
  不用先写一张表。
- **权限**:能调哪些工具由身份算(与 `/mcp` 的 `tools/list` 同一条判据
  `tool_visible`),再被会话自己的白名单收窄一层。会话只能越用越窄:签的时候
  不能超过这个人手上的权限,改的时候也一样。
- **允许**:会话开了 `confirm`,改世界的调用不直接执行,落成一条待批的调用;
  人点了允许才走出口。只读口(名字以 `.read` 结尾的能力)不受这条约束 ——
  看一眼不需要批准,也就不用把人也拉过来点一下。

loop 不自己写:推一版、看一眼、改主意的循环交给 `bub.core.Agent`,它带工具执行、
多步、事件流。平台这一侧只剩"出口"这一件事,和沙箱里那个 agent 完全相同。
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from engine.auth import ALL_PERMISSIONS, is_write_permission
from engine.auth.keys import is_scoped, permission_for_tool, tool_visible

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


_SESSIONS: dict[str, ConsoleSession] = {}


def _sweep() -> None:
    for key in [k for k, s in _SESSIONS.items() if s.expired()]:
        _SESSIONS.pop(key, None)


def reset() -> None:
    """测试用:清空进程内的会话。"""
    _SESSIONS.clear()


def sessions() -> dict[str, ConsoleSession]:
    _sweep()
    return _SESSIONS


def get_session(session_id: str) -> ConsoleSession:
    _sweep()
    found = _SESSIONS.get(session_id)
    if found is None:
        raise SessionError("这个会话已经不在了(进程重启或闲置太久),重新开一个")
    found.touch()
    return found


def _held_permissions(actor: Any) -> frozenset[str]:
    """这个人手上有哪些权限。会话能给出去的,不会超过这一份。

    静态令牌没有权限集(只有 read/operate),它对"能签什么"的回答是全部或没有。
    这一条与 `grantable` 的口径一致,免得同一个部署里两种说法。
    """
    if actor is None:
        return frozenset(ALL_PERMISSIONS)
    if is_scoped(actor):
        return frozenset(getattr(actor, "permissions", frozenset()))
    from engine.auth import PERMISSIONS

    return frozenset(PERMISSIONS) if getattr(actor, "scope", "") == "operate" else frozenset()


def _refuse_overreach(wanted: set[str], granted: frozenset[str], what: str) -> None:
    over = sorted(wanted - granted)
    if over:
        raise SessionError(f"你手上没有这些{what},给不出去:{', '.join(over)}")


def open_session(
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
    _SESSIONS[session.id] = session
    return session


def update_session(
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
    return session


def close_session(session_id: str) -> bool:
    return _SESSIONS.pop(session_id, None) is not None


# ---------------------------------------------------------------------------
# 权限:一个工具在这个会话里能不能用
# ---------------------------------------------------------------------------


def session_allows(session: ConsoleSession, tool: str, bindings_of: Any = None) -> bool:
    """这个会话够不够得着这个工具。

    判据全在 `tool_visible`:权限集、身份自带的白名单、资源三关。会话再收窄一层。
    这里不重写一遍权限表 —— 第二份判据迟早与第一份打架。
    """
    from engine.api.auth import Actor

    proxy = Actor(
        token_id="console",
        name=session.actor,
        tenant=session.tenant,
        scope="operate" if any(is_write_permission(p) for p in session.permissions) else "read",
        permissions=session.permissions,
        bindings=session.bindings,
    )
    if not tool_visible(tool, proxy, bindings_of):
        return False
    return not session.tools or tool in session.tools


def describe_tools(session: ConsoleSession, registry: Any) -> list[dict[str, Any]]:
    """会话看到的工具清单。与 `/mcp` 的 `tools/list` 同一份事实来源:出口清单。"""
    from engine.agent.tools import tool_specs

    out: list[dict[str, Any]] = []
    for spec in tool_specs(registry):
        function = spec.get("function") or {}
        name = str(function.get("name") or "")
        if not name or not session_allows(session, name, getattr(registry, "tool_bindings", None)):
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


def bub_tools(session: ConsoleSession, registry: Any) -> list[Any]:
    """把会话的工具清单翻成 bub 的 `Tool`。

    参数 schema 直接用出口清单给的那份 —— 参数名来自插件声明,不是这里编的。
    `additionalProperties` 打开:出口清单只说了"有这些参数",没说"只能有这些"。
    """
    from bub.core.tools import Tool

    out: list[Tool] = []
    for spec in describe_tools(session, registry):
        name = model_tool_name(str(spec["name"]))
        parameters = dict(spec["parameters"] or {"type": "object", "properties": {}})
        parameters.setdefault("type", "object")
        parameters["additionalProperties"] = True
        out.append(
            Tool(
                name=name,
                handler=_make_handler(session, registry, name),
                description=str(spec["description"]),
                parameters=parameters,
            )
        )
    return out


def _make_handler(session: ConsoleSession, registry: Any, model_name: str):
    capability = capability_of(model_name)

    async def handler(**kwargs: Any) -> dict[str, Any]:
        return await call_tool(session, registry, capability, kwargs)

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
    session: ConsoleSession, registry: Any, name: str, args: dict[str, Any]
) -> dict[str, Any]:
    """一次工具调用。只读直接做,改世界的要人点允许。

    人点拒绝、超时、次数用完都是**结论**,不是异常:它们原样回到模型手里,
    模型据此换办法或者收尾。抛出只会让这轮对话断在半路。
    """
    from engine.agent.tools import ToolCall, run_tool
    from engine.change_unit import create_ledger

    args = dict(args or {})
    if not session_allows(session, name, getattr(registry, "tool_bindings", None)):
        return ToolResult(
            False, reason=f"这个会话没有 {permission_for_tool(name)} 权限,或者够不着它作用的那几个资源"
        ).to_dict()

    effects = registry.declared_effects()
    mutating = name in effects

    if mutating and session.confirm:
        return await ask(session, name, args)

    if mutating:
        if session.actions >= MAX_ACTIONS:
            return ToolResult(
                False, reason=f"这次对话已经改了 {session.actions} 次,到上限 {MAX_ACTIONS} 了;停手,由人接手"
            ).to_dict()
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
    return result.to_dict()


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


async def ask(session: ConsoleSession, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """把这次调用摆到人面前,等到他点。

    这里等的是**人**,不是锁:同一个人可以有多个会话,但一个会话只有一次在等。
    """
    import asyncio

    if pending_of(session) is not None:
        return ToolResult(False, reason="上一个动作还在等人点,先处理它").to_dict()

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
        return ToolResult(False, reason="人等急了,这个动作没点允许,当作没做").to_dict()
    if call.decision == "deny":
        return ToolResult(False, reason=call.reason or "人不同意这个动作").to_dict()

    if session.actions >= MAX_ACTIONS:
        return ToolResult(
            False, reason=f"这次对话已经改了 {session.actions} 次,到上限 {MAX_ACTIONS} 了;停手,由人接手"
        ).to_dict()
    session.actions += 1
    from engine.agent.tools import ToolCall, run_tool
    from engine.change_unit import create_ledger

    registry = _registry()
    result = await run_tool(
        ToolCall(name, args),
        registry=registry,
        ledger=create_ledger(),
        tenant=session.tenant,
        binding=session.binding,
        summary=call.summary or f"控制台助手调用 {name}",
        actor=session.actor,
    )
    return result.to_dict()


def _registry() -> Any:
    from engine.plugin_manager import registry

    return registry


def decide(session: ConsoleSession, call_id: str, allow: bool, reason: str = "") -> PendingCall:
    """人点了。由前端那条批准接口调用,判据只有一条:这个会话确实有这么一次在等。"""
    found = _PENDING.get(call_id)
    if found is None or found[0] is not session:
        raise SessionError("这次调用已经不在等你了(超时,或者不在这个会话里)")
    call = found[1]
    if call.decision:
        raise SessionError("这次调用已经点过了")
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
    "ToolResult",
    "ask",
    "bub_tools",
    "call_tool",
    "close_session",
    "decide",
    "describe_pending",
    "describe_tools",
    "get_session",
    "open_session",
    "pending_of",
    "reset",
    "reset_pending",
    "session_allows",
    "sessions",
    "update_session",
]
