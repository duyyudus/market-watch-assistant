from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api_server.app.schemas import WatchlistCreate, WatchlistUpdate
from common.config import Settings
from common.db.models import MarketSymbolResolution, WatchlistEntity
from common.external_providers import ProviderRetryPolicy
from common.market_symbol_resolver import (
    resolve_watchlist_market_symbol,
    watchlist_resolution_fields_changed,
)


def _attach_resolution(
    entry: WatchlistEntity,
    resolution: MarketSymbolResolution | None,
) -> WatchlistEntity:
    entry.market_data_resolution = resolution
    return entry


async def _resolve_interactive(
    session: AsyncSession,
    entry: WatchlistEntity,
    *,
    settings: Settings | None,
) -> MarketSymbolResolution:
    async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
        return await resolve_watchlist_market_symbol(
            session,
            entry,
            settings=settings,
            client=client,
            retry_policy=ProviderRetryPolicy(max_retries=0, delays=()),
        )


async def list_watchlist(session: AsyncSession) -> list[WatchlistEntity]:
    rows = list(
        (await session.scalars(select(WatchlistEntity).order_by(WatchlistEntity.name.asc()))).all()
    )
    if not rows:
        return rows
    resolutions = list(
        (
            await session.scalars(
                select(MarketSymbolResolution).where(
                    MarketSymbolResolution.watchlist_entity_id.in_([row.id for row in rows])
                )
            )
        ).all()
    )
    by_entry_id = {resolution.watchlist_entity_id: resolution for resolution in resolutions}
    return [_attach_resolution(row, by_entry_id.get(row.id)) for row in rows]


async def create_watchlist(
    session: AsyncSession,
    payload: WatchlistCreate,
    *,
    settings: Settings | None = None,
) -> WatchlistEntity:
    entry = WatchlistEntity(**payload.model_dump())
    session.add(entry)
    await session.flush()
    resolution = await _resolve_interactive(session, entry, settings=settings)
    await session.refresh(entry)
    _attach_resolution(entry, resolution)
    return entry


async def update_watchlist(
    session: AsyncSession,
    entry: WatchlistEntity,
    payload: WatchlistUpdate,
    *,
    settings: Settings | None = None,
) -> WatchlistEntity:
    values = payload.model_dump(exclude_unset=True)
    should_resolve = watchlist_resolution_fields_changed(set(values))
    for key, value in values.items():
        setattr(entry, key, value)
    await session.flush()
    resolution = None
    if should_resolve:
        resolution = await _resolve_interactive(session, entry, settings=settings)
    else:
        resolution = await session.scalar(
            select(MarketSymbolResolution).where(
                MarketSymbolResolution.watchlist_entity_id == entry.id
            )
        )
    await session.refresh(entry)
    _attach_resolution(entry, resolution)
    return entry


async def delete_watchlist(session: AsyncSession, entry: WatchlistEntity) -> None:
    await session.delete(entry)
    await session.flush()
