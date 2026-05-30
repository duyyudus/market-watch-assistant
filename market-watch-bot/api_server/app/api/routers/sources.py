from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from api_server.app.api.dependencies import SessionDep
from api_server.app.schemas import ListEnvelope, SourceCreate, SourceRead, SourceUpdate
from api_server.app.services import sources as source_service
from common.db.models import NewsSource

router = APIRouter()


@router.get("/sources", response_model=ListEnvelope[SourceRead])
async def list_sources(
    session: SessionDep,
    enabled: bool | None = None,
) -> ListEnvelope[SourceRead]:
    rows = await source_service.list_sources(session, enabled=enabled)
    return ListEnvelope(items=[SourceRead.model_validate(row) for row in rows], total=len(rows))


@router.post("/sources", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: SourceCreate,
    session: SessionDep,
) -> SourceRead:
    source = await source_service.create_source(session, payload)
    return SourceRead.model_validate(source)


@router.patch("/sources/{source_id}", response_model=SourceRead)
async def update_source(
    source_id: str,
    payload: SourceUpdate,
    session: SessionDep,
) -> SourceRead:
    source = await session.get(NewsSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source = await source_service.update_source(session, source, payload)
    return SourceRead.model_validate(source)


@router.post("/sources/{source_id}/enable", response_model=SourceRead)
async def enable_source(
    source_id: str, session: SessionDep
) -> SourceRead:
    return await set_source_enabled(source_id, True, session)


@router.post("/sources/{source_id}/disable", response_model=SourceRead)
async def disable_source(
    source_id: str, session: SessionDep
) -> SourceRead:
    return await set_source_enabled(source_id, False, session)


async def set_source_enabled(
    source_id: str,
    enabled: bool,
    session: SessionDep,
) -> SourceRead:
    source = await session.get(NewsSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source = await source_service.set_source_enabled(session, source, enabled)
    return SourceRead.model_validate(source)


@router.get("/source-fetch-logs")
async def source_fetch_logs(
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, object]:
    rows, total = await source_service.list_source_fetch_logs(session, limit=limit)
    return {"items": [row.__dict__ for row in rows], "total": total}
