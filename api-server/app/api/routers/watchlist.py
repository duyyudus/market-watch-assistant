from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import SessionDep
from app.models import WatchlistEntity
from app.schemas import ListEnvelope, WatchlistCreate, WatchlistRead, WatchlistUpdate
from app.services import watchlist as watchlist_service

router = APIRouter()


@router.get("/watchlist", response_model=ListEnvelope[WatchlistRead])
async def list_watchlist(
    session: SessionDep,
) -> ListEnvelope[WatchlistRead]:
    rows = await watchlist_service.list_watchlist(session)
    return ListEnvelope(items=[WatchlistRead.model_validate(row) for row in rows], total=len(rows))


@router.post("/watchlist", response_model=WatchlistRead, status_code=status.HTTP_201_CREATED)
async def create_watchlist(
    payload: WatchlistCreate,
    session: SessionDep,
) -> WatchlistRead:
    entry = await watchlist_service.create_watchlist(session, payload)
    return WatchlistRead.model_validate(entry)


@router.patch("/watchlist/{entry_id}", response_model=WatchlistRead)
async def update_watchlist(
    entry_id: str,
    payload: WatchlistUpdate,
    session: SessionDep,
) -> WatchlistRead:
    entry = await session.get(WatchlistEntity, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    entry = await watchlist_service.update_watchlist(session, entry, payload)
    return WatchlistRead.model_validate(entry)


@router.delete("/watchlist/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(
    entry_id: str,
    session: SessionDep,
) -> None:
    entry = await session.get(WatchlistEntity, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    await watchlist_service.delete_watchlist(session, entry)
