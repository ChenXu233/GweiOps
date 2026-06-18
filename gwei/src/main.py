# src/main.py
from fastapi import FastAPI
from src.api.webhook import router as webhook_router
from src.api.health import router as health_router

app = FastAPI(
    title="既未 · Gwei",
    description="AI 驱动的 GitHub Issue 修复平台",
    version="0.1.0",
)

app.include_router(webhook_router)
app.include_router(health_router)
