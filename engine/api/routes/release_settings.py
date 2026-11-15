# engine/api/routes/release_settings.py
"""发布配置的页面读写口 —— 让「这个仓库怎么发布」在控制台就能改。

发布配置按「出厂 → 部署环境 → 租户默认(key=*) → 仓库行(key=owner/repo)」四层逐键
合并,解析在 [release.py](../../workflows/release.py)。这里只管后两层的读写:
value 是一个 JSON 对象,整行读、整行写、整行删,不存在字段级 diff——
发布配置没有密钥,一次存进去就是一份完整声明。

出厂默认与环境变量在 GET 里以 effective 兜底出现:页面先展示「现在实际会怎样」,
再展示每层自己配了什么,填不填都不破坏既有部署。
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from engine.api.auth import by_of, require, tenant_scope
from engine.shared.config import config
from engine.shared.settings_store import create_settings_store
from engine.workflows.release import (
    MODES,
    _COMPOSE_REQUIRED,
    _RELEASE_SCOPE,
    _template_fields,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# 页面展示的字段与一句话说明;词表与含义随 release.py 走,这里不另立一份。
RELEASE_FIELD_DESCRIPTIONS = {
    "mode": f"发布模式:off 合并只记报告,compose 走发布管道;可选 {', '.join(MODES)}",
    "project_dir": "compose 项目目录",
    "service": "compose 服务名",
    "image_template": "镜像模板,支持 {repo} / {sha} / {number}",
    "binding": "发布效果打到的下游目标",
    "base_branch": "只发布合入该基线的 PR;空 = 任意基线",
}


class ReleaseValuesDTO(BaseModel):
    """一行发布配置。字段由 release.py 的模式决定,这里不逐个点名。"""

    model_config = ConfigDict(extra="allow")

    values: dict[str, str] = {}


def _validate_values(values: dict[str, str]) -> list[str]:
    """写入前校验。返回错误文案列表;空串不算覆盖,拦的只是存进去会炸的形状。"""
    errors: list[str] = []
    mode = values.get("mode", "")
    if mode.strip() and mode not in MODES:
        errors.append(
            f"mode：只能是 {', '.join(MODES)}（当前的发布模式词表）"
        )
    if "image_template" in values:
        template = values["image_template"]
        if template.strip():
            try:
                fields = _template_fields(template)
            except ValueError:
                errors.append("image_template：不是合法模板")
            else:
                unknown = fields - {"repo", "sha", "number"}
                if unknown:
                    errors.append(
                        "image_template：含不认识的占位符 " + "、".join(sorted(unknown))
                        + "（支持 {repo} / {sha} / {number}）"
                    )
    unknown_keys = set(values) - set(RELEASE_FIELD_DESCRIPTIONS)
    if unknown_keys:
        errors.append(
            "不认识的键 " + "、".join(sorted(unknown_keys)) + "（可填:"
            + "、".join(RELEASE_FIELD_DESCRIPTIONS) + "）"
        )
    return errors


def _row_json(raw: str) -> dict | None:
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _request_tenant(request: Request) -> str:
    """页面在改哪个租户的发布配置。

    与 settings_scopes 的公共值不同:发布解析按 payload 的 tenant_slug 走,事件没带
    租户时落在 default_tenant_slug。页面没有鉴权租户声明时跟随它,不然页面写的是
    公共层、引擎读的是租户层,填了等于没填。
    """
    return tenant_scope(request, None) or config.settings.default_tenant_slug


def _layer_info(values: dict[str, str] | None) -> dict:
    if not values:
        return {"set": False, "values": {}}
    return {
        "set": True,
        "values": {k: str(v) for k, v in values.items()},
    }


@router.get("/api/settings/release")
async def get_release_config(request: Request) -> dict:
    """这个租户的发布配置:生效值在前,每一层自己配了什么在后。"""
    require(request, "settings.read")
    tenant = _request_tenant(request)
    from engine.workflows.release import resolve_release_config

    default_row = _row_json(config.stored(_RELEASE_SCOPE, tenant).get("*", ""))
    repo_rows = {
        key: row
        for key, raw in config.stored(_RELEASE_SCOPE, tenant).items()
        if key != "*" and (row := _row_json(raw)) is not None
    }
    effective = resolve_release_config(tenant)
    return {
        "fields": RELEASE_FIELD_DESCRIPTIONS,
        "modes": list(MODES),
        "compose_required": list(_COMPOSE_REQUIRED),
        "effective": effective,
        "tenant_default": _layer_info(default_row),
        "repos": {
            key: {"effective": resolve_release_config(tenant, key), **_layer_info(row)}
            for key, row in sorted(repo_rows.items())
        },
    }


@router.put("/api/settings/release/tenant-default")
async def put_tenant_default(body: ReleaseValuesDTO, request: Request) -> dict:
    return await _put_row("*", body, request)


@router.put("/api/settings/release/repos/{repo_full_name:path}")
async def put_repo_row(repo_full_name: str, body: ReleaseValuesDTO, request: Request) -> dict:
    if "/" not in repo_full_name or repo_full_name.count("/") != 1:
        raise HTTPException(
            status_code=400,
            detail=f"仓库行按 owner/repo 写,收到的是 {repo_full_name!r}",
        )
    return await _put_row(repo_full_name, body, request)


@router.delete("/api/settings/release/tenant-default")
async def delete_tenant_default(request: Request) -> dict:
    return await _delete_row("*", request)


@router.delete("/api/settings/release/repos/{repo_full_name:path}")
async def delete_repo_row(repo_full_name: str, request: Request) -> dict:
    return await _delete_row(repo_full_name, request)


async def _put_row(key: str, body: ReleaseValuesDTO, request: Request) -> dict:
    require(request, "settings.write")
    values = {str(k): str(v) for k, v in body.values.items()}
    if not values:
        raise HTTPException(status_code=400, detail="没有要写入的值")
    errors = _validate_values(values)
    if errors:
        raise HTTPException(status_code=422, detail="；".join(errors))

    tenant = _request_tenant(request)
    store = create_settings_store()
    await store.put(
        _RELEASE_SCOPE,
        {key: json.dumps(values, ensure_ascii=False)},
        by=by_of(request, ""),
        tenant=tenant,
    )
    merged = config.all_stored()
    merged.setdefault(tenant, {}).setdefault(_RELEASE_SCOPE, {})[key] = json.dumps(
        values, ensure_ascii=False
    )
    config.apply_stored(merged)

    from engine.auth import audit

    identity = getattr(request.state, "identity", None)
    await audit.record(
        "settings.write",
        identity=identity,
        target=f"{_RELEASE_SCOPE}:{key}",
        detail={"keys": sorted(values), "tenant": tenant},
        ip=request.client.host if request.client else "",
    )

    from engine.workflows.release import resolve_release_config

    return {
        "key": key,
        "values": values,
        "effective": resolve_release_config(tenant, key if key != "*" else ""),
    }


async def _delete_row(key: str, request: Request) -> dict:
    require(request, "settings.write")
    tenant = _request_tenant(request)
    removed = await create_settings_store().delete(_RELEASE_SCOPE, key, tenant=tenant)
    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"没有这行发布配置: {key}"
            + (f"(租户 {tenant})" if tenant else "(公共)"),
        )
    config.forget(_RELEASE_SCOPE, key, tenant)
    from engine.workflows.release import resolve_release_config

    return {
        "removed": key,
        "effective": resolve_release_config(tenant, key if key != "*" else ""),
    }
