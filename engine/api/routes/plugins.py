# engine/api/routes/plugins.py
"""插件清单与启停 API —— 前端插件页与 UI 插槽的数据源。

- `GET /api/plugins` 列发现到的全部清单(含未启用的),`enabled` 表示它此刻在不在流程里;
- `GET /api/plugins/widgets` 只取已启用插件声明的卡片。

启停是运行期的事:打开 = 导入 + 注册 + on_startup,关掉 = on_shutdown + 摘索引。
决定写进库里,下次启动按它来。
"""

import logging
import mimetypes
from pathlib import PurePosixPath

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from engine.api.auth import actor_of, by_of, require, tenant_scope
from engine.api.schemas import MetricDTO, PluginDTO, PluginWidgetDTO
from engine.plugin_manager import tenancy
from engine.plugin_manager.registry import registry
from engine.shared.metrics import metrics

router = APIRouter()
logger = logging.getLogger(__name__)


def _requested_tenant(request: Request) -> str:
    """这次调用代表哪个租户。令牌声明的租户优先;两者冲突是越权,不是覆盖。"""
    declared = request.query_params.get("tenant") or None
    return tenant_scope(request, declared) or ""


def _plugin_dto(state, tenant: str) -> PluginDTO:
    manifest = state.manifest
    return PluginDTO(
        name=manifest.name,
        version=manifest.version,
        type=manifest.type.value,
        description=manifest.description,
        capabilities=manifest.capabilities,
        widgets=[w.to_dict() for w in manifest.ui_widgets],
        pages=[p.to_dict() for p in manifest.ui_pages],
        enabled=state.enabled,
        platform_available=state.platform_available,
        tenant_enabled=state.tenant_enabled,
        instances=state.instances,
        reason=state.reason,
        error=state.error,
    )


def _state_of(name: str, tenant: str = ""):
    for state in registry.states(tenant=tenant):
        if state.manifest.name == name:
            return state
    return None


@router.get("/api/plugins")
async def list_plugins(request: Request) -> list[PluginDTO]:
    """发现到的全部清单,含未启用的。

    两层决定分开给:`platform_available` 是部署级,`tenant_enabled` 是调用者所在
    租户的选择。前端一个开关只能表达一件事,所以这点必须由接口说清楚。
    """
    require(request, "plugins.read")
    tenant = _requested_tenant(request)
    return [_plugin_dto(state, tenant) for state in registry.states(tenant=tenant)]


@router.get("/api/plugins/widgets")
async def list_widgets(
    request: Request, slot: str = Query("issue-board.bento")
) -> list[PluginWidgetDTO]:
    require(request, "plugins.read")
    tenant = _requested_tenant(request)
    widgets: list[dict] = []
    for state in registry.states(tenant=tenant):
        if not state.enabled:
            continue
        for w in state.manifest.ui_widgets:
            if w.slot != slot:
                continue
            entry = w.to_dict()
            entry["plugin"] = state.manifest.name
            # 实时值:metric 条目声明 metric.name 时以收集器当前值填充
            for metric in entry.get("metrics", []):
                ref = metric.get("metric")
                if isinstance(ref, dict) and ref.get("name"):
                    metric["value"] = metrics.sum_metric(
                        ref["name"], ref.get("labels")
                    )
            widgets.append(PluginWidgetDTO(**entry))
    return widgets


@router.get("/api/metrics")
async def list_metrics(prefix: str = Query("")) -> list[MetricDTO]:
    """指标快照(最新值序列),供插件页面经桥只读拉取。"""
    rows = metrics.snapshot(prefix=prefix or None)
    return [
        MetricDTO(name=m.name, labels=m.labels, value=m.value)
        for m in sorted(rows, key=lambda m: m.name)
    ]


@router.post("/api/plugins/{name}/enable")
async def enable_plugin(name: str, request: Request) -> PluginDTO:
    """打开一个插件。

    两层:平台没提供它就是 409(租户开不了平台关掉的东西);平台提供了,开的
    是这个租户的选择(`plugin_tenancy`),不写全局。
    """
    require(request, "plugins.write")
    tenant = _requested_tenant(request)
    _require_platform_offers(name)

    try:
        await registry.enable(name)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 - 导入或实例化失败是插件自己的问题
        logger.error("启用插件 %s 失败: %s", name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"{name} 装载失败:{e}") from e

    await _remember_tenant(name, True, tenant, by_of(request, ""))
    return _plugin_dto(_state_of(name, tenant), tenant)


@router.post("/api/plugins/{name}/disable")
async def disable_plugin(name: str, request: Request) -> PluginDTO:
    require(request, "plugins.write")
    tenant = _requested_tenant(request)
    try:
        await registry.disable(name)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    await _remember_tenant(name, False, tenant, by_of(request, ""))
    return _plugin_dto(_state_of(name, tenant), tenant)


@router.post("/api/plugins/rescan")
async def rescan_plugins(request: Request) -> dict:
    """重扫插件目录:新出现的按决定启用,磁盘上没了的停用,已在跑且没变的不动。"""
    require(request, "plugins.write")
    outcome = registry.rescan()
    # 重扫之后把新出现且该启用的实例启动起来
    for name in outcome["added"]:
        state = _state_of(name)
        if state is not None and state.enabled:
            await registry.enable(name)
    return outcome


def _require_platform_offers(name: str) -> None:
    """平台没提供这个插件时,租户点开它是配置错误,不是权限问题——409 说清楚。"""
    for state in registry.states():
        if state.manifest.name == name:
            if not state.platform_available:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"{name} 在这个部署里没有提供({state.reason});"
                        "租户只能在自己拿得到的插件里选,打开平台关掉的插件要改部署配置"
                    ),
                )
            return
    raise HTTPException(status_code=404, detail=f"没有发现插件:{name}")


async def _remember_tenant(name: str, enabled: bool, tenant: str, by: str) -> None:
    """把租户级决定写进库,并让它立刻影响解析。

    写库失败只告警:开关在本次进程里已生效,差别只是活不过重启——这句话要说出来,
    不能让人以为存下来了。
    """
    registry.set_tenant_decisions(tenant, {name: enabled})
    try:
        await tenancy.save(tenant, name, enabled, by=by)
    except Exception:  # noqa: BLE001 - 库不可用只告警
        logger.warning(
            "租户 %s 的插件启停决定没存下来(%s=%s),重启后会回到平台默认",
            tenant or "<全局>",
            name,
            enabled,
        )


@router.get("/api/plugins/{name}/ui/{file_path:path}")
async def plugin_ui_asset(name: str, file_path: str, request: Request) -> FileResponse:
    """服务插件自带 UI 资产;resolve 后必须仍位于插件 ui 目录内,越界与缺失一律 404。"""
    require(request, "plugins.read")
    plugin_dir = registry.plugin_dir(name)
    manifest = registry.manifest(name)
    if plugin_dir is None or manifest is None or not manifest.ui_pages:
        raise HTTPException(status_code=404, detail="Plugin UI not found")

    ui_root = (plugin_dir / "ui").resolve()
    # PurePosixPath 防止 Windows 盘符/反斜杠形态的路径逃逸
    candidate = (ui_root / PurePosixPath(file_path)).resolve()
    if not candidate.is_relative_to(ui_root):
        raise HTTPException(status_code=404, detail="Plugin UI not found")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Plugin UI not found")

    media_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
    return FileResponse(candidate, media_type=media_type)
