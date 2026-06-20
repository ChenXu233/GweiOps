# src/api/health.py
from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
async def health_check():
    return {"status": "healthy", "version": "0.1.0"}
