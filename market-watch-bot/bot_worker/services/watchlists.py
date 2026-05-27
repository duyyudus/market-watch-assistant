from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import (
    NewsEntity,
    WatchlistEntity,
)
from bot_worker.watchlist import WatchlistEntry


async def news_item_entities(session: AsyncSession, news_item_id: str) -> list[str]:
    rows = list(
        (
            await session.scalars(
                select(NewsEntity).where(NewsEntity.news_item_id == news_item_id)
            )
        ).all()
    )
    return [row.normalized_name for row in rows]


async def news_item_tickers(session: AsyncSession, news_item_id: str) -> list[str]:
    rows = list(
        (
            await session.scalars(
                select(NewsEntity).where(NewsEntity.news_item_id == news_item_id)
            )
        ).all()
    )
    return [row.ticker for row in rows if row.ticker]


async def watchlist_entries(session: AsyncSession) -> list[WatchlistEntry]:
    rows = list(
        (
            await session.scalars(select(WatchlistEntity).where(WatchlistEntity.enabled.is_(True)))
        ).all()
    )
    return [
        WatchlistEntry(
            symbol=row.symbol,
            name=row.name,
            tier=row.tier,
            entity_type=row.entity_type,
            region=row.region,
            asset_class=row.asset_class,
            aliases=row.aliases,
            enabled=row.enabled,
        )
        for row in rows
    ]
async def add_watchlist_entry(
    session: AsyncSession,
    *,
    name: str,
    symbol: str | None,
    tier: str,
    entity_type: str,
    region: str | None,
    asset_class: str | None,
    aliases: list[str],
) -> WatchlistEntity:
    entry = WatchlistEntity(
        name=name,
        symbol=symbol,
        tier=tier,
        entity_type=entity_type,
        region=region,
        asset_class=asset_class,
        aliases=aliases,
    )
    session.add(entry)
    await session.flush()
    return entry
