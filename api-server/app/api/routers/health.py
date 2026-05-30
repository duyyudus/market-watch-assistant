from __future__ import annotations

from fastapi import APIRouter

from app.config import load_settings

router = APIRouter()
settings = load_settings()


@router.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "service": settings.app.name,
        "environment": settings.app.environment,
    }
