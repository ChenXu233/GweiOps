# engine/api/app.py
"""FastAPI 应用入口 - 既未 · Gwei。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from engine.api.routes.health import router as health_router
from engine.api.routes.webhook import router as webhook_router
from engine.api.routes.webhook import get_adapter, get_sensor

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理 - startup 初始化插件，shutdown 关闭插件。"""
    # Startup: 初始化插件
    logger.info("Initializing plugins...")
    adapter = get_adapter()
    sensor = get_sensor()

    try:
        await adapter.on_startup()
        logger.info("GitHubAppAdapter initialized")
    except Exception as e:
        logger.error(f"Failed to initialize GitHubAppAdapter: {e}")

    try:
        await sensor.on_startup()
        logger.info("SensorAgent initialized")
    except Exception as e:
        logger.error(f"Failed to initialize SensorAgent: {e}")

    yield

    # Shutdown: 关闭插件
    logger.info("Shutting down plugins...")
    try:
        await adapter.on_shutdown()
        logger.info("GitHubAppAdapter shutdown")
    except Exception as e:
        logger.error(f"Failed to shutdown GitHubAppAdapter: {e}")

    try:
        await sensor.on_shutdown()
        logger.info("SensorAgent shutdown")
    except Exception as e:
        logger.error(f"Failed to shutdown SensorAgent: {e}")


app = FastAPI(
    title="既未 · Gwei",
    description="AI 驱动的 GitHub Issue 修复平台",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(webhook_router)
