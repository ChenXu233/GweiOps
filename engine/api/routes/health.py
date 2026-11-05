# src/api/health.py
from fastapi import APIRouter

from engine.api.schemas import HealthDTO

router = APIRouter()


@router.get("/api/health")
async def health_check() -> HealthDTO:
    return HealthDTO(status="healthy", version="0.1.0")