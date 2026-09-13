# engine/api/routes/plugins.py
"""插件清单 API —— 前端插件市场与 UI 插槽的数据源。

数据来自插件注册表(内存),只读;注册表未发现时返回空列表而非报错,
保证前端在插件加载完成前可正常渲染骨架。
"""

import logging
import mimetypes
from pathlib import PurePosixPath

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from engine.plugin_manager.registry import registry
from engine.shared.metrics import metrics

router = APIRouter()
logger = logging.getLogger(__name__)


def _plugin_dto(name: str) -> dict:
    manifest = registry.manifest(name)
    return {
        "name": manifest.name,
        "version": manifest.version,
        "type": manifest.type.value,
        "description": manifest.description,
        "capabilities": manifest.capabilities,
        "widgets": [w.to_dict() for w in manifest.ui_widgets],
        "pages": [p.to_dict() for p in manifest.ui_pages],
    }


@router.get("/api/plugins")
async def list_plugins() -> list[dict]:
    if not registry.names():
        return []
    return [_plugin_dto(name) for name in registry.names()]


@router.get("/api/plugins/widgets")
async def list_widgets(slot: str = Query("dashboard.bento")) -> list[dict]:
    widgets: list[dict] = []
    for name in registry.names():
        manifest = registry.manifest(name)
        for w in manifest.ui_widgets:
            if w.slot != slot:
                continue
            entry = w.to_dict()
            entry["plugin"] = manifest.name
            # 实时值:metric 条目声明 metric.name 时以收集器当前值填充
            for metric in entry.get("metrics", []):
                ref = metric.get("metric")
                if isinstance(ref, dict) and ref.get("name"):
                    metric["value"] = metrics.sum_metric(
                        ref["name"], ref.get("labels")
                    )
            widgets.append(entry)
    return widgets


@router.get("/api/metrics")
async def list_metrics(prefix: str = Query("")) -> list[dict]:
    """指标快照(最新值序列),供插件页面经桥只读拉取。"""
    rows = metrics.snapshot(prefix=prefix or None)
    return [
        {"name": m.name, "labels": m.labels, "value": m.value}
        for m in sorted(rows, key=lambda m: m.name)
    ]


@router.get("/api/plugins/{name}/ui/{file_path:path}")
async def plugin_ui_asset(name: str, file_path: str) -> FileResponse:
    """服务插件自带 UI 资产(将来鉴权/能力令牌的挂钩点在 engine 侧)。

    安全:resolve 后必须仍位于插件 ui 目录内,越界与缺失一律 404。
    """
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
