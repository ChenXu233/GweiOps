# engine/api/routes/plugins.py
"""插件清单 API —— 前端插件市场与 UI 插槽的数据源。

数据来自插件注册表(内存),只读;注册表未发现时返回空列表而非报错,
保证前端在插件加载完成前可正常渲染骨架。
"""

import logging

from fastapi import APIRouter, Query

from engine.plugin_manager.registry import registry

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
        "pages": manifest.ui_pages,
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
            widgets.append(entry)
    return widgets
