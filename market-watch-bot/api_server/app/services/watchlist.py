from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api_server.app.schemas import WatchlistCreate, WatchlistUpdate
from common.db.models import WatchlistEntity


async def list_watchlist(session: AsyncSession) -> list[WatchlistEntity]:
    return list(
        (await session.scalars(select(WatchlistEntity).order_by(WatchlistEntity.name.asc()))).all()
    )


async def create_watchlist(session: AsyncSession, payload: WatchlistCreate) -> WatchlistEntity:
    entry = WatchlistEntity(**payload.model_dump())
    session.add(entry)
    await session.flush()
    await session.refresh(entry)
    return entry


async def update_watchlist(
    session: AsyncSession,
    entry: WatchlistEntity,
    payload: WatchlistUpdate,
) -> WatchlistEntity:
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, key, value)
    await session.flush()
    await session.refresh(entry)
    return entry


async def delete_watchlist(session: AsyncSession, entry: WatchlistEntity) -> None:
    await session.delete(entry)
    await session.flush()
