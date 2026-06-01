from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from api_server.app.api.dependencies import SessionDep
from api_server.app.schemas import EventDetailRead, EventRead, ListEnvelope
from api_server.app.services import events as event_service
from common.db.models import EventCluster

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


@router.get("/events/stream")
async def event_stream(
    session: SessionDep,
    replay: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
) -> StreamingResponse:
    async def generate():
        for item in await event_service.list_stream_events(session, replay=replay, limit=limit):
            yield _sse_message(str(item["event"]), item["data"])
        cursor = event_service.stream_cursor_now()
        heartbeat_after = 15
        elapsed = 0
        while not replay:
            changes, cursor = await event_service.list_stream_events_since(
                session,
                since=cursor,
                limit=limit,
            )
            for item in changes:
                yield _sse_message(str(item["event"]), item["data"])
            if elapsed >= heartbeat_after:
                yield _sse_message("heartbeat", {"status": "ok"})
                elapsed = 0
            await asyncio.sleep(2)
            elapsed += 2

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/events/{event_id}")
async def get_event(
    event_id: str,
    session: SessionDep,
) -> EventDetailRead:
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


def _sse_message(event_name: str, data: object) -> str:
    payload = json.dumps(data, default=str, separators=(",", ":"))
    return f"event: {event_name}\ndata: {payload}\n\n"
