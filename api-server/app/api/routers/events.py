from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.dependencies import SessionDep
from app.models import EventCluster
from app.schemas import EventRead, ListEnvelope
from app.services import events as event_service

router = APIRouter()


@router.get("/events", response_model=ListEnvelope[EventRead])
async def list_events(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
    q: str | None = None,
) -> ListEnvelope[EventRead]:
    rows, total = await event_service.list_events(
        session, limit=limit, offset=offset, status_filter=status_filter, q=q
    )
    return ListEnvelope(items=[EventRead.model_validate(row) for row in rows], total=total)


@router.get("/events/{event_id}")
async def get_event(
    event_id: str,
    session: SessionDep,
) -> dict[str, object]:
    event = await session.get(EventCluster, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return await event_service.get_event_detail(session, event)


@router.get("/score-history/{event_id}")
async def score_history(
    event_id: str,
    session: SessionDep,
) -> dict[str, object]:
    rows = await event_service.list_event_score_history(session, event_id=event_id)
    return {"items": [row.__dict__ for row in rows], "total": len(rows)}
