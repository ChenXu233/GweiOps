# engine/agent/tools.py
"""出口 —— 沙箱里的 agent 唯一能改变外部世界的地方。

模型能干什么,上限由它的沙箱决定,不由这张工具表决定。沙箱里它该有 shell、
编辑器、跑测试、翻日志的自由:修代码、复现问题、写补丁,没有这些它做不了事。
拿权限去砍它,只会砍出一个不会修东西的助理。

所以这里不限制"它能做什么",只划一件事:**什么算离开沙箱**。

- 声明了效果的能力 = 出口。每次调用落成一个变更单元,走完整条闸门:
  读窗口 → 判定 → 执行 → 验证 → 一行账。改生产只能从这里过。
- 名字以 `.read` 结尾的能力 = 只读口。看一眼,不落账。

这条边界靠结构成立,不靠自觉:沙箱里没有生产凭据,凭据只在提供者手里。
沙箱是可丢弃的;出口只有这几个。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.change_unit import (
    VERDICT_KEPT,
    ChangeUnit,
    apply as apply_unit,
)

READ_SUFFIX = ".read"


@dataclass(frozen=True)
class ToolCall:
    """一次出口调用。名字就是能力名。"""

    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """回给 agent 的结果。它必须能读懂,所以 verdict 与 reason 原样带回去。"""

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


def is_mutating(capability: str, menu: dict[str, dict[str, Any]]) -> bool:
    return capability in menu


def tool_specs(registry: Any) -> list[dict[str, Any]]:
    """出口的清单:改世界的在前,只读的在后。

    参数名来自清单声明,类型不声明——清单只说了"有这些参数",没说什么类型。
    """
    specs: list[dict[str, Any]] = []
    for capability, decl in sorted(registry.declared_effects().items()):
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": capability,
                    "description": (
                        f"{decl.get('label') or capability}。"
                        "调用会改变外部世界,平台先判定此刻还能不能撤回。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {name: {} for name in decl.get("args") or []},
                        "additionalProperties": False,
                    },
                },
            }
        )

    for capability in sorted(_read_capabilities(registry)):
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": capability,
                    "description": "只读,不改外部世界。",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": True,
                    },
                },
            }
        )
    return specs


def _read_capabilities(registry: Any) -> list[str]:
    out: list[str] = []
    for name in getattr(registry, "names", lambda: [])():
        manifest = registry.manifest(name)
        for capability in getattr(manifest, "capabilities", []) or []:
            if capability.endswith(READ_SUFFIX) and capability not in out:
                out.append(capability)
    return out


async def run_tool(
    call: ToolCall,
    *,
    registry: Any,
    ledger: Any = None,
    tenant: str = "",
    binding: str = "",
    idem_base: str = "",
    index: int = 0,
    summary: str = "",
    actor: str = "",
    incident_id: str = "",
    policy: Any = None,
) -> ToolResult:
    """走一次出口。改世界的过闸门,只读的直接调。

    失败一律变成结果返回,不往上抛:沙箱里的 agent 看到"被拦了、为什么",
    才能换个办法;抛出只会让它的会话断在半路。
    """
    args = dict(call.args or {})
    menu = registry.declared_effects()

    if not is_mutating(call.name, menu):
        try:
            data = await registry.run_capability(call.name, args)
        except LookupError as exc:
            return ToolResult(False, reason=f"没有这个出口: {exc}")
        except Exception as exc:  # noqa: BLE001 - 失败要回到 agent 手里,不是回到调用栈里
            return ToolResult(False, reason=f"出口调用失败: {type(exc).__name__}: {exc}")
        return ToolResult(True, data=data if isinstance(data, dict) else {"result": data})

    try:
        provider, decl = registry.effect_decl(
            call.name, tenant=tenant, binding=binding
        )
    except LookupError as exc:
        return ToolResult(
            False, reason=f"这个目标上没有能执行 {call.name} 的提供者: {exc}"
        )

    intent: dict[str, Any] = {
        "summary": summary or f"agent 调用 {call.name}",
        "tool": call.name,
        "via": "exit",  # 从出口进来的变更,数量上限按它统计
    }
    if actor:
        intent["by"] = actor

    unit = ChangeUnit(
        intent=intent,
        effect=decl.to_effect(args),
        tenant=tenant,
        binding=binding,
        incident_id=incident_id,
        idempotency_key=f"{idem_base}:tool:{index}" if idem_base else "",
    )
    try:
        outcome = await apply_unit(unit, provider, ledger, policy=policy)
    except Exception as exc:  # noqa: BLE001 - 闸门自己崩了,也要回给 agent
        return ToolResult(False, reason=f"推进失败: {type(exc).__name__}: {exc}")

    return ToolResult(
        ok=outcome.verdict == VERDICT_KEPT,
        verdict=outcome.verdict,
        reason=outcome.reason,
        data={"unit_id": outcome.id, "handle": outcome.handle},
    )


__all__ = ["ToolCall", "ToolResult", "tool_specs", "run_tool", "is_mutating"]
