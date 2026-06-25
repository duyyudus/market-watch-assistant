from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api_server.app.schemas import WatchlistCreate, WatchlistUpdate
from api_server.app.services.events import (
    event_read_payload,
    report_range_subquery,
    report_ranges_by_event_id,
)
from common.config import Settings
from common.db.models import EventCluster, MarketSymbolResolution, WatchlistEntity, utcnow
from common.external_providers import ProviderRetryPolicy
from common.market_symbol_resolver import (
    resolve_watchlist_market_symbol,
    watchlist_resolution_fields_changed,
)

SPOTLIGHT_TIERS = {"S", "A", "TIER-1", "TIER1", "1"}


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


def _spotlight_term(value: str | None) -> str:
    return (value or "").strip().casefold()


def _spotlight_terms(values: list[str | None]) -> set[str]:
    return {term for value in values if (term := _spotlight_term(value))}


def _event_matches_watchlist_entry(event: EventCluster, entry: WatchlistEntity) -> bool:
    affected_tickers = _spotlight_terms(event.affected_tickers or [])
    symbol = _spotlight_term(entry.symbol)
    if symbol:
        return symbol in affected_tickers

    affected_entities = _spotlight_terms(event.affected_entities or [])
    entity_terms = _spotlight_terms([entry.name, *(entry.aliases or [])])
    return bool(entity_terms & affected_entities)


def _event_spotlight_time(
    event: EventCluster,
    report_range: tuple[datetime | None, datetime | None] | None,
) -> datetime:
    _report_start_at, report_end_at = report_range or (None, None)
    value = report_end_at or event.last_updated_at or event.created_at
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def list_watchlist_spotlight(
    session: AsyncSession,
    *,
    per_asset_limit: int,
    since_hours: int,
) -> list[dict[str, object]]:
    entries = [
        entry
        for entry in await list_watchlist(session)
        if entry.enabled and _spotlight_term(entry.tier).upper() in SPOTLIGHT_TIERS
    ]
    if not entries:
        return []

    cutoff = utcnow() - timedelta(hours=since_hours)
    report_ranges_query = report_range_subquery()
    report_time = func.coalesce(
        report_ranges_query.c.report_end_at,
        EventCluster.last_updated_at,
        EventCluster.created_at,
    )
    events = list(
        (
            await session.scalars(
                select(EventCluster)
                .outerjoin(
                    report_ranges_query,
                    report_ranges_query.c.event_cluster_id == EventCluster.id,
                )
                .where(report_time >= cutoff)
                .order_by(
                    report_time.desc(),
                    EventCluster.final_score.desc(),
                    EventCluster.last_updated_at.desc(),
                    EventCluster.created_at.desc(),
                )
            )
        ).all()
    )
    report_ranges = await report_ranges_by_event_id(session, [event.id for event in events])
    sorted_events = sorted(
        events,
        key=lambda event: (
            _event_spotlight_time(event, report_ranges.get(event.id)),
            event.final_score,
        ),
        reverse=True,
    )

    spotlight: list[dict[str, object]] = []
    for entry in entries:
        matches = [
            event for event in sorted_events if _event_matches_watchlist_entry(event, entry)
        ]
        if not matches:
            continue
        spotlight.append(
            {
                "entry": entry,
                "events": [
                    event_read_payload(event, report_start_at=start_at, report_end_at=end_at)
                    for event in matches[:per_asset_limit]
                    for start_at, end_at in [report_ranges.get(event.id, (None, None))]
                ],
                "total": len(matches),
            }
        )
    return spotlight


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
