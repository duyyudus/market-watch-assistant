from __future__ import annotations

from collections import defaultdict
from datetime import UTC, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api_server.app.schemas import SourceCreate, SourceHealthRead, SourceUpdate
from common.db.models import NewsSource, SourceFetchLog, utcnow


async def list_sources(session: AsyncSession, *, enabled: bool | None) -> list[NewsSource]:
    stmt = select(NewsSource).order_by(NewsSource.name.asc())
    if enabled is not None:
        stmt = stmt.where(NewsSource.enabled.is_(enabled))
    return list((await session.scalars(stmt)).all())


async def create_source(session: AsyncSession, payload: SourceCreate) -> NewsSource:
    source = NewsSource(
        name=payload.name,
        url=str(payload.url),
        region=payload.region,
        category=payload.category,
        source_type=payload.source_type,
        language=payload.language,
        source_score=payload.source_score,
        polling_interval_seconds=payload.polling_interval_seconds,
        asset_classes=[payload.category],
        enabled=payload.enabled,
    )
    session.add(source)
    await session.flush()
    await session.refresh(source)
    return source


async def update_source(
    session: AsyncSession,
    source: NewsSource,
    payload: SourceUpdate,
) -> NewsSource:
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(source, key, str(value) if key == "url" else value)
    if "category" in updates:
        source.asset_classes = [source.category]
    await session.flush()
    await session.refresh(source)
    return source


async def set_source_enabled(
    session: AsyncSession,
    source: NewsSource,
    enabled: bool,
) -> NewsSource:
    source.enabled = enabled
    await session.flush()
    await session.refresh(source)
    return source


async def set_all_sources_enabled(session: AsyncSession, *, enabled: bool) -> list[NewsSource]:
    await session.execute(update(NewsSource).values(enabled=enabled))
    await session.flush()
    return await list_sources(session, enabled=None)


async def list_source_fetch_logs(
    session: AsyncSession, *, limit: int
) -> tuple[list[SourceFetchLog], int]:
    rows = list(
        (
            await session.scalars(
                select(SourceFetchLog).order_by(SourceFetchLog.fetched_at.desc()).limit(limit)
            )
        ).all()
    )
    return rows, len(rows)


async def list_source_health(session: AsyncSession) -> list[SourceHealthRead]:
    sources = await list_sources(session, enabled=None)
    since = utcnow() - timedelta(days=7)
    logs = list(
        (
            await session.scalars(
                select(SourceFetchLog)
                .where(SourceFetchLog.fetched_at >= since)
                .order_by(SourceFetchLog.fetched_at.desc())
            )
        ).all()
    )
    logs_by_source: dict[str, list[SourceFetchLog]] = defaultdict(list)
    for log in logs:
        logs_by_source[log.source_id].append(log)

    rows: list[SourceHealthRead] = []
    for source in sources:
        source_logs = logs_by_source.get(source.id, [])
        latest = source_logs[0] if source_logs else None
        durations = [log.duration_ms for log in source_logs if log.duration_ms is not None]
        daily_counts: dict[str, int] = defaultdict(int)
        for log in source_logs:
            day = log.fetched_at.astimezone(UTC).date().isoformat()
            daily_counts[day] += int(log.item_count or 0)
        if not source.enabled:
            health_status = "disabled"
        elif source.consecutive_failure_count >= 3 or latest and latest.status == "error":
            health_status = "failing"
        elif source.consecutive_failure_count > 0:
            health_status = "degraded"
        else:
            health_status = "healthy"
        rows.append(
            SourceHealthRead(
                source_id=source.id,
                name=source.name,
                enabled=source.enabled,
                category=source.category,
                region=source.region,
                health_status=health_status,
                latest_status=latest.status if latest else None,
                last_fetched_at=latest.fetched_at if latest else source.last_fetched_at,
                consecutive_failure_count=source.consecutive_failure_count,
                average_latency_ms=round(sum(durations) / len(durations)) if durations else None,
                daily_item_counts=[
                    {"date": day, "count": daily_counts[day]} for day in sorted(daily_counts)
                ],
            )
        )
    return rows
