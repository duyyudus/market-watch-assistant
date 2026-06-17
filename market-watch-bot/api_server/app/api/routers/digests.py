from __future__ import annotations

from fastapi import APIRouter, Query

from api_server.app.api.dependencies import SessionDep
from api_server.app.schemas import DigestRead, EventRead, ListEnvelope
from api_server.app.services import events as event_service

router = APIRouter()


@router.get("/digests/preview", response_model=ListEnvelope[EventRead])
async def digest_preview(
    session: SessionDep,
    limit: int = Query(20, ge=1, le=100),
) -> ListEnvelope[EventRead]:
    rows = await event_service.list_digest_preview(session, limit=limit)
    return ListEnvelope(items=[EventRead.model_validate(row) for row in rows], total=len(rows))


@router.get("/digests/latest", response_model=DigestRead | None)
async def latest_digest(session: SessionDep) -> DigestRead | None:
    digest = await event_service.get_latest_digest(session)
    return DigestRead.model_validate(digest) if digest is not None else None
