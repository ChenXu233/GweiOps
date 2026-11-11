# engine/api/routes/settings_scopes.py
"""插件声明的配置项 —— 要填什么、填了没有、哪些能看见。

**回显是字段自己的事**,不是接口一刀切:每个字段声明 `expose`(never / masked / always)
与 `read_scope`(read / operate)。没声明的默认 never——没写的就不出去。

值存在业务库,改了就生效,重启不丢。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, ValidationError

from engine.api.auth import actor_of, by_of, tenant_scope
from engine.shared.config import config, mask_value
from engine.shared.settings_store import create_settings_store

router = APIRouter()
logger = logging.getLogger(__name__)


class ScopeFieldDTO(BaseModel):
    """一个配置项。value 只在它自己允许回显、且调用方够得着的时候才出现。"""

    name: str
    required: bool = False
    expose: str = "never"
    read_scope: str = "read"
    set: bool = False
    value: str | None = None
    # 这个字段该填什么,给人看的一句话(来自模型字段的 description)
    description: str = ""
    # 值带换行(私钥):页面用多行输入,不然粘贴时换行会被吃掉
    multiline: bool = False


class ScopeDTO(BaseModel):
    name: str
    prefix: str = ""
    fields: list[ScopeFieldDTO]
    missing: list[str]


class ScopeValuesDTO(BaseModel):
    """要写进去的一组键值。字段名由声明决定,这里不预设。"""

    model_config = ConfigDict(extra="allow")

    values: dict[str, str] = {}


def _shown(spec, raw: str | None, caller_scope: str) -> str | None:
    """这个字段现在该不该把值给出去。"""
    if raw in (None, ""):
        return None
    if spec.expose == "never":
        return None
    if spec.read_scope == "operate" and caller_scope != "operate":
        return None
    return mask_value(str(raw)) if spec.expose == "masked" else str(raw)


@router.get("/api/settings/scopes")
async def list_scopes(request: Request) -> list[ScopeDTO]:
    actor = actor_of(request)
    caller_scope = actor.scope if actor else "operate"
    tenant = tenant_scope(request, None) or ""
    out: list[ScopeDTO] = []
    for scope in config.list_scopes():
        values = config.get_scope_config(scope.name, tenant)
        fields = []
        for spec in config.field_specs(scope.name, tenant):
            raw = values.get(spec.name)
            fields.append(
                ScopeFieldDTO(
                    name=spec.name,
                    required=spec.required,
                    expose=spec.expose,
                    read_scope=spec.read_scope,
                    set=raw not in (None, ""),
                    multiline=spec.multiline,
                    value=_shown(spec, raw, caller_scope),
                    description=spec.description,
                )
            )
        out.append(
            ScopeDTO(
                name=scope.name,
                prefix=scope.prefix,
                fields=fields,
                missing=config.validate_scope(scope.name, tenant),
            )
        )
    return out


# 校验失败时给人看的话:字段名 + 应该怎么填。pydantic 的英文原文留给日志,不甩给用户。
_REASON_TEXT = {
    "string_pattern_mismatch": "格式不对",
    "string_too_short": "太短了",
    "string_too_long": "太长了",
    "string_type": "需要是文本",
    "int_parsing": "需要是整数",
    "int_type": "需要是整数",
    "int_from_float": "需要是整数",
    "float_parsing": "需要是数字",
    "float_type": "需要是数字",
    "bool_parsing": "需要是 true 或 false",
    "literal_error": "只能填给定选项",
    "url_parsing": "不是合法网址",
    "missing": "必填",
}

# 这几类错误直接拿字段说明当答案,比"格式不对"有用得多。
_HINT_FIRST = {"string_pattern_mismatch", "url_parsing", "literal_error"}


def _explain(exc: ValidationError, scope_name: str, tenant: str) -> str:
    hints = {spec.name: spec.description for spec in config.field_specs(scope_name, tenant)}
    parts: list[str] = []
    for err in exc.errors():
        loc = [str(x) for x in (err.get("loc") or []) if x != "__root__"]
        field = ".".join(loc) or "配置"
        hint = hints.get(field, "")
        kind = str(err.get("type") or "")
        if kind in _HINT_FIRST and hint:
            reason = hint
        else:
            reason = _REASON_TEXT.get(kind) or "填的值不合法"
            if hint:
                reason = f"{reason}（{hint}）"
        parts.append(f"{field}：{reason}")
    return "；".join(parts) or "配置不合法"


@router.put("/api/settings/scopes/{scope_name}")
async def put_scope(scope_name: str, body: ScopeValuesDTO, request: Request) -> dict:
    if config.get_scope(scope_name) is None:
        raise HTTPException(status_code=404, detail=f"没有这个配置 scope: {scope_name}")
    values = {str(key): str(value) for key, value in body.values.items()}
    if not values:
        raise HTTPException(status_code=400, detail="没有要写入的值")

    tenant = tenant_scope(request, None) or ""
    try:
        config.validate_values(scope_name, values, tenant)
    except ValidationError as exc:
        logger.info("settings scope %s rejected: %s", scope_name, exc)
        raise HTTPException(
            status_code=422, detail=_explain(exc, scope_name, tenant)
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    stored = await create_settings_store().put(
        scope_name, values, by=by_of(request, ""), tenant=tenant
    )
    merged = config.all_stored()
    merged.setdefault(tenant, {})[scope_name] = stored
    config.apply_stored(merged)

    return {
        "scope": scope_name,
        "set": sorted(stored),
        "missing": config.validate_scope(scope_name, tenant),
    }


@router.delete("/api/settings/scopes/{scope_name}/{key}")
async def delete_value(scope_name: str, key: str, request: Request) -> dict:
    """删掉一个键。删了租户的那一份,读的时候落回公共值——不是落空。"""
    if config.get_scope(scope_name) is None:
        raise HTTPException(status_code=404, detail=f"没有这个配置 scope: {scope_name}")
    tenant = tenant_scope(request, None) or ""

    removed = await create_settings_store().delete(scope_name, key, tenant=tenant)
    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"{scope_name} 上没有这个键: {key}"
            + (f"(租户 {tenant})" if tenant else "(公共)"),
        )
    config.forget(scope_name, key, tenant)

    return {
        "scope": scope_name,
        "removed": key,
        "set": sorted(config.stored(scope_name, tenant)),
        "missing": config.validate_scope(scope_name, tenant),
    }
