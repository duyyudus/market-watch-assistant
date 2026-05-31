from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from api_server.app.api.dependencies import SessionDep, SettingsDep
from api_server.app.db import get_engine
from common.db.session import pool_metrics

router = APIRouter()


@router.get("/health")
async def health(settings: SettingsDep) -> dict[str, object]:
    return {
        "status": "ok",
        "service": settings.app.name,
        "environment": settings.app.environment,
    }


@router.get("/ready", response_model=None)
async def ready(
    request: Request,
    session: SessionDep,
):
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": "unavailable", "error": str(exc)},
        )
    return {
        "status": "ready",
        "database": "ok",
        "pool": pool_metrics(get_engine(request)),
    }
