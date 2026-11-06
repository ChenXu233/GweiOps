# engine/api/routes/settings_scopes.py
"""插件声明的配置项 —— 看得到要填什么、填得进去、读回来不回显值。

配置不是部署那一刻定死的:值存在业务库,改了就生效,重启不丢。
谁声明的字段谁负责解释;平台只负责存、读、以及告诉你还缺什么。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from engine.api.auth import by_of
from engine.shared.config import config
from engine.shared.settings_store import create_settings_store

router = APIRouter()


class ScopeValuesDTO(BaseModel):
    """要写进去的一组键值。字段名由声明决定,这里不预设。"""

    model_config = ConfigDict(extra="allow")

    values: dict[str, str] = {}


@router.get("/api/settings/scopes")
async def list_scopes(request: Request) -> list[dict]:
    """每个 scope:要填什么、填了没有、缺什么。值一律不回显。"""
    out = []
    for scope in config.list_scopes():
        out.append(
            {
                "name": scope.name,
                "prefix": scope.prefix,
                "required": list(scope.required_keys),
                "optional": list(scope.optional_keys),
                "set": sorted(config.stored(scope.name)),
                "missing": config.validate_scope(scope.name),
            }
        )
    return out


@router.put("/api/settings/scopes/{scope_name}")
async def put_scope(scope_name: str, body: ScopeValuesDTO, request: Request) -> dict:
    if config.get_scope(scope_name) is None:
        raise HTTPException(status_code=404, detail=f"没有这个配置 scope: {scope_name}")
    values = {str(key): str(value) for key, value in body.values.items()}
    if not values:
        raise HTTPException(status_code=400, detail="没有要写入的值")

    stored = await create_settings_store().put(
        scope_name, values, by=by_of(request, "")
    )
    merged = config.all_stored()
    merged[scope_name] = stored
    config.apply_stored(merged)

    return {
        "scope": scope_name,
        "set": sorted(stored),
        "missing": config.validate_scope(scope_name),
    }
