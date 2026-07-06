from __future__ import annotations

from fastapi import APIRouter, Query

from api_server.app.api.dependencies import SessionDep
from api_server.app.schemas import ListEnvelope, MarketMoveRead
from api_server.app.services import operations as operation_service

router = APIRouter()


@router.get("/market/moves", response_model=ListEnvelope[MarketMoveRead])
async def market_moves(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
) -> ListEnvelope[MarketMoveRead]:
    rows, total = await operation_service.list_market_moves(session, limit=limit)
    return ListEnvelope(
        items=[MarketMoveRead.model_validate(row) for row in rows],
        total=total,
    )
