# engine/api/routes/plugins.py
"""插件清单与启停 API —— 前端插件页与 UI 插槽的数据源。

两条读口问的是不同的事:

- `GET /api/plugins` 列**发现到的**清单(含未启用的),`enabled` 说它此刻在不在流程里;
- `GET /api/plugins/widgets` 只取**已启用**插件声明的卡片——一张卡片只有在插件
  活着的时候才拿得到数,不该在页面上留一个永远"暂时取不到"的格子。

启停是运行期的事:打开 = 导入 + 注册 + on_startup,关掉 = on_shutdown + 摘索引,
不用重启进程。决定写进库里,下次启动按它来。
"""

import logging
import mimetypes
from pathlib import PurePosixPath

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from engine.api.auth import by_of, require
from engine.api.schemas import MetricDTO, PluginDTO, PluginWidgetDTO
from engine.plugin_manager import enablement
from engine.plugin_manager.registry import registry
from engine.shared.metrics import metrics

router = APIRouter()
logger = logging.getLogger(__name__)


def _plugin_dto(state) -> PluginDTO:
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
        instances=state.instances,
        reason=state.reason,
        error=state.error,
    )


def _state_of(name: str):
    for state in registry.states():
        if state.manifest.name == name:
            return state
    return None


@router.get("/api/plugins")
async def list_plugins(request: Request) -> list[PluginDTO]:
    """发现到的全部清单。未启用的也在里面——否则页面上没有地方把它打开。"""
    require(request, "plugins.read")
    return [_plugin_dto(state) for state in registry.states()]


@router.get("/api/plugins/widgets")
async def list_widgets(
    request: Request, slot: str = Query("issue-board.bento")
) -> list[PluginWidgetDTO]:
    require(request, "plugins.read")
    widgets: list[dict] = []
    for state in registry.states():
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
    """打开一个已发现但没启用的插件。

    没有清单就 404:目录里根本没有这个东西,给它记一条"已启用"只会让下次启动
    对着一行谁也对不上的配置发呆。
    """
    require(request, "plugins.write")
    try:
        await registry.enable(name)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 - 导入或实例化失败是插件自己的问题
        logger.error("启用插件 %s 失败: %s", name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"{name} 装载失败:{e}") from e

    await _remember(name, True, by_of(request, ""))
    return _plugin_dto(_state_of(name))


@router.post("/api/plugins/{name}/disable")
async def disable_plugin(name: str, request: Request) -> PluginDTO:
    require(request, "plugins.write")
    try:
        await registry.disable(name)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    await _remember(name, False, by_of(request, ""))
    return _plugin_dto(_state_of(name))


@router.post("/api/plugins/rescan")
async def rescan_plugins(request: Request) -> dict:
    """重扫插件目录:新出现的按决定启用,已经删掉的停用。已在跑且没变的不动。"""
    require(request, "plugins.write")
    outcome = registry.rescan()
    # 重扫之后把"新出现且该启用"的实例启动起来(启动期那次不分青红皂白都会启动)
    for name in outcome["added"]:
        state = _state_of(name)
        if state is not None and state.enabled:
            await registry.enable(name)
    return outcome


async def _remember(name: str, enabled: bool, by: str) -> None:
    """把决定写进库。写不进去只告警:开关已经生效了,差别只是能不能活过重启。"""
    try:
        await enablement.save_decision(name, enabled, by=by)
    except Exception:  # noqa: BLE001 - 库不可用不该让这次启停整体失败
        logger.warning("插件的启停决定没存下来(%s=%s),重启后会回到清单默认", name, enabled)


@router.get("/api/plugins/{name}/ui/{file_path:path}")
async def plugin_ui_asset(name: str, file_path: str, request: Request) -> FileResponse:
    """服务插件自带 UI 资产(将来鉴权/能力令牌的挂钩点在 engine 侧)。

    安全:resolve 后必须仍位于插件 ui 目录内,越界与缺失一律 404。
    权限与同组其它端点一致,由 `require` 拦——同一组接口不该有两种口径。
    """
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
