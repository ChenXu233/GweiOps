# engine/api/routes/api_keys.py
"""密钥管理 —— 给人签一把万用钥匙,给 agent 用的那种。

签发的对象是"外界的 agent"(Claude Code、Cursor、dsh):它拿一个 URL 加一把密钥
就能接上 `/mcp`。这把密钥有什么权限,它的工具清单里就只有什么工具。

三条规则写在这里,不靠界面提示:

1. **签出去的权限不能超过自己的**。owner 可以签全量,别人只能签自己有效权限的子集
   ——和控制台里建子用户是同一条红线。
2. **明文只出现一次**。响应里给一次,之后只留 hint(前缀…后缀)与哈希。
3. **吊销立即生效**,记录留着:谁签的、什么时候用过,还看得见。签错了也吊销——
   明文只出现一次,签错的那把除了吊销没有第二种处理。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from engine.api.auth import actor_of, require, tenant_scope
from engine.api.schemas import (
    KeyCreateDTO,
    KeyDTO,
    KeyIssuedDTO,
    KeyListDTO,
    KeyResourceListDTO,
    KeyToolDTO,
    KeyToolListDTO,
    ResourceDTO,
)
from engine.auth import PERMISSIONS
from engine.auth import audit
from engine.auth import keys as key_store

router = APIRouter()
logger = logging.getLogger(__name__)


def _identity_tenant(request: Request) -> str:
    """这一把该落在谁的账上。令牌与密钥的租户优先;都空就只有默认租户。"""
    from engine.shared.config import config

    tenant = tenant_scope(request, None)
    if tenant:
        return tenant
    identity = getattr(request.state, "identity", None)
    if identity is not None and identity.tenant:
        return identity.tenant
    return config.settings.default_tenant_slug


def _grantable(request: Request) -> frozenset[str] | None:
    """这个人最多能签出去什么。None = 不限(没有任何身份,单机自用)。"""
    from engine.api.auth import auth_required

    actor = actor_of(request)
    if actor is None:
        if auth_required():
            raise HTTPException(status_code=401, detail="未登录或令牌无效")
        return None
    from engine.auth.keys import is_scoped

    if is_scoped(actor):
        return actor.permissions
    # 静态令牌只有 scope:operate 能签全量,read 一条也签不出去
    return frozenset(PERMISSIONS) if actor.can_write else frozenset()


def _check_grantable(request: Request, wanted: list[str]) -> list[str]:
    unknown = [p for p in wanted if p not in PERMISSIONS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"没有这些权限:{', '.join(unknown)}")
    allowed = _grantable(request)
    if allowed is None:
        return sorted(set(wanted))
    over = sorted(set(wanted) - set(allowed))
    if over:
        raise HTTPException(
            status_code=403, detail=f"你手上没有这些权限,签不出去:{', '.join(over)}"
        )
    return sorted(set(wanted))


@router.get("/api/keys/resources")
async def list_key_resources(request: Request) -> KeyResourceListDTO:
    """这个部署里的资源(下游目标)。签密钥时给人挑,不是权限目录。

    资源名由插件实例自己声明(`binding`),平台不认识全集,所以这里是"出现过
    哪些",不是"允许哪些"。
    """
    require(request, "keys.read")
    from engine.plugin_manager import registry
    from engine.shared.config import config

    caps = registry.resource_capabilities() if hasattr(registry, "resource_capabilities") else {}
    return KeyResourceListDTO(
        resources=[
            ResourceDTO(key=binding, capabilities=items)
            for binding, items in sorted(caps.items())
        ],
        default=config.settings.default_binding,
    )


@router.get("/api/keys/tools")
async def list_key_tools(request: Request) -> KeyToolListDTO:
    """能授予的工具:每个要什么权限、能作用在哪些资源上。

    页面靠它画"资源 × 工具"那张表 —— 前端不再自己猜哪个工具属于哪个目标。
    """
    require(request, "keys.read")
    from engine.agent import tool_specs
    from engine.auth.keys import permission_for_tool
    from engine.plugin_manager import registry

    effects = registry.declared_effects()
    items: list[KeyToolDTO] = []
    for spec in tool_specs(registry):
        function = spec.get("function") or {}
        name = str(function.get("name") or "")
        if not name:
            continue
        items.append(
            KeyToolDTO(
                name=name,
                label=str((effects.get(name) or {}).get("label") or name),
                permission=permission_for_tool(name),
                resources=list(registry.tool_bindings(name))
                if hasattr(registry, "tool_bindings")
                else [],
                mutating=name in effects,
            )
        )
    return KeyToolListDTO(tools=items)


@router.get("/api/keys")
async def list_keys(request: Request) -> KeyListDTO:
    require(request, "keys.read")
    records = await key_store.list_keys(_identity_tenant(request))
    return KeyListDTO(
        items=[KeyDTO(**record.to_dict()) for record in records], total=len(records)
    )


@router.post("/api/keys")
async def create_key(payload: KeyCreateDTO, request: Request) -> KeyIssuedDTO:
    require(request, "keys.manage")
    permissions = _check_grantable(request, payload.permissions)
    tenant = _identity_tenant(request)
    actor = actor_of(request)
    try:
        record, plaintext = await key_store.create_key(
            tenant=tenant,
            name=payload.name,
            permissions=permissions,
            tools=payload.tools,
            bindings=payload.bindings,
            created_by=(actor.name if actor else ""),
            expires_at=payload.expires_at,
        )
    except key_store.KeyError_ as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    logger.info(
        "key issued %s [%s] by %s permissions=%s",
        record.hint,
        tenant or "-",
        actor.name if actor else "-",
        ",".join(sorted(record.permissions)) or "-",
    )
    await audit.record(
        "key.create",
        identity=getattr(request.state, "identity", None),
        target=record.id,
        detail={
            "hint": record.hint,
            "permissions": sorted(record.permissions),
            "tools": sorted(record.tools),
            "bindings": sorted(record.bindings),
        },
        ip=request.client.host if request.client else "",
    )
    return KeyIssuedDTO(**record.to_dict(), key=plaintext)


@router.delete("/api/keys/{key_id}")
async def revoke_key(key_id: str, request: Request) -> dict:
    """吊销。之后这把密钥的每个请求都是 401,记录留着。"""
    require(request, "keys.manage")
    tenant = _identity_tenant(request)
    if not await key_store.revoke_key(tenant, key_id):
        raise HTTPException(status_code=404, detail="没有这把密钥")
    await audit.record(
        "key.revoke",
        identity=getattr(request.state, "identity", None),
        target=key_id,
        detail={"tenant": tenant},
        ip=request.client.host if request.client else "",
    )
    return {"revoked": key_id}


__all__ = ["router"]
