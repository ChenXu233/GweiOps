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

from engine.api.auth import actor_of, by_of
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
    out: list[ScopeDTO] = []
    for scope in config.list_scopes():
        values = config.get_scope_config(scope.name)
        fields = []
        for spec in config.field_specs(scope.name):
            raw = values.get(spec.name)
            fields.append(
                ScopeFieldDTO(
                    name=spec.name,
                    required=spec.required,
                    expose=spec.expose,
                    read_scope=spec.read_scope,
                    set=raw not in (None, ""),
                    value=_shown(spec, raw, caller_scope),
                )
            )
        out.append(
            ScopeDTO(
                name=scope.name,
                prefix=scope.prefix,
                fields=fields,
                missing=config.validate_scope(scope.name),
            )
        )
    return out


@router.put("/api/settings/scopes/{scope_name}")
async def put_scope(scope_name: str, body: ScopeValuesDTO, request: Request) -> dict:
    if config.get_scope(scope_name) is None:
        raise HTTPException(status_code=404, detail=f"没有这个配置 scope: {scope_name}")
    values = {str(key): str(value) for key, value in body.values.items()}
    if not values:
        raise HTTPException(status_code=400, detail="没有要写入的值")

    try:
        config.validate_values(scope_name, values)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    stored = await create_settings_store().put(scope_name, values, by=by_of(request, ""))
    merged = config.all_stored()
    merged[scope_name] = stored
    config.apply_stored(merged)

    return {
        "scope": scope_name,
        "set": sorted(stored),
        "missing": config.validate_scope(scope_name),
    }
