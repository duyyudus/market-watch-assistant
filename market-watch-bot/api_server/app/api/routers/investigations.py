from __future__ import annotations

from fastapi import APIRouter, Query

from api_server.app.api.dependencies import SessionDep
from api_server.app.services import operations as operation_service

router = APIRouter()


@router.get("/investigations")
async def investigations(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, object]:
    rows, total = await operation_service.list_investigations(session, limit=limit)
    return {"items": [row.__dict__ for row in rows], "total": total}
