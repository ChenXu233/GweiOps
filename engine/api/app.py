# engine/api/app.py
"""FastAPI 应用入口 - 既未 · Gwei。"""

import logging
from contextlib import asynccontextmanager

from dbos import DBOS, DBOSConfig
from fastapi import FastAPI

from engine.api.routes.health import router as health_router
from engine.api.routes.plugins import router as plugins_router
from engine.api.routes.webhook import router as webhook_router
from engine.plugin_manager import registry
from engine.shared.config import config
import engine.workflows.pipeline as pipeline  # noqa: F401 — 导入即注册 DBOS 工作流/步骤

logger = logging.getLogger(__name__)

# DBOS 持久化执行：系统表位于同一 Postgres 实例的独立 dbos schema，
# URL 归一为同步驱动（DBOS 内部使用 psycopg）。
dbos = DBOS(
    config=DBOSConfig(
        name=config.settings.app_name,
        system_database_url=config.settings.database_url.replace("+asyncpg", ""),
    )
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理 - startup 初始化插件注册表与 DBOS,shutdown 逆序关闭。"""
    # Startup: 发现并启动全部插件(失败隔离,单插件故障不阻止引擎启动)
    registry.discover()
    await registry.launch()

    # Startup: 启动 DBOS 并注册工作流队列(按租户分区,公平性执行点)
    logger.info("Launching DBOS...")
    DBOS.launch()
    await DBOS.register_queue_async(pipeline.WORKFLOW_QUEUE, partition_concurrency=4)
    logger.info("DBOS launched (partitioned queue: %s)", pipeline.WORKFLOW_QUEUE)

    yield

    # Shutdown: 先停工作流执行器,再停插件
    logger.info("Shutting down DBOS...")
    dbos.destroy()

    logger.info("Shutting down plugins...")
    await registry.shutdown()


app = FastAPI(
    title="既未 · Gwei",
    description="AI 驱动的 GitHub Issue 修复平台",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(plugins_router)
app.include_router(webhook_router)
