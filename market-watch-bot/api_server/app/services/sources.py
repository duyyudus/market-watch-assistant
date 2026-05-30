from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api_server.app.schemas import SourceCreate, SourceUpdate
from common.db.models import NewsSource, SourceFetchLog


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
    await session.commit()
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
    await session.commit()
    await session.refresh(source)
    return source


async def set_source_enabled(
    session: AsyncSession,
    source: NewsSource,
    enabled: bool,
) -> NewsSource:
    source.enabled = enabled
    await session.commit()
    await session.refresh(source)
    return source


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
