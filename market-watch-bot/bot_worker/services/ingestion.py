from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import (
    NewsSource,
    NormalizedNewsItem,
    RawNewsItem,
)
from bot_worker.normalize import (
    canonicalize_url,
    content_hash,
    normalize_datetime,
    normalize_text,
    title_hash,
)
from bot_worker.rss import ParsedFeedItem
from bot_worker.services.common import _json_safe, _published_to_string


def is_rss_item_fresh(
    *,
    published_at: datetime | None,
    fetched_at: datetime,
    now: datetime,
    freshness_hours: int,
) -> bool:
    effective_time = published_at or fetched_at
    if effective_time.tzinfo is None:
        effective_time = effective_time.replace(tzinfo=UTC)
    return effective_time >= now - timedelta(hours=freshness_hours)
def raw_item_from_parsed(source: NewsSource, item: ParsedFeedItem) -> RawNewsItem:
    raw_text = " ".join([item.title, item.description, item.url])
    return RawNewsItem(
        source_id=source.id,
        raw_title=item.title,
        raw_description=item.description,
        raw_url=item.url,
        raw_published_at=_published_to_string(item.published),
        raw_payload=_json_safe(item.raw_payload),
        content_hash=content_hash(raw_text),
    )
async def normalize_pending_raw_items(
    session: AsyncSession, *, limit: int = 500, freshness_hours: int = 72
) -> int:
    stmt = (
        select(RawNewsItem, NewsSource)
        .join(NewsSource, NewsSource.id == RawNewsItem.source_id)
        .outerjoin(NormalizedNewsItem, NormalizedNewsItem.raw_item_id == RawNewsItem.id)
        .where(NormalizedNewsItem.id.is_(None))
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    inserted = 0
    now = datetime.now(UTC)
    for raw, source in rows:
        title = normalize_text(raw.raw_title)
        if not title or not raw.raw_url:
            continue
        published_at = normalize_datetime(raw.raw_published_at)
        if not is_rss_item_fresh(
            published_at=published_at,
            fetched_at=raw.fetched_at,
            now=now,
            freshness_hours=freshness_hours,
        ):
            continue
        snippet = normalize_text(raw.raw_description)
        canonical_url = canonicalize_url(raw.raw_url)
        item = NormalizedNewsItem(
            source_id=source.id,
            raw_item_id=raw.id,
            title=title,
            snippet=snippet or None,
            url=raw.raw_url,
            canonical_url=canonical_url,
            source_name=source.name,
            source_type=source.source_type,
            source_score=source.source_score,
            published_at=published_at,
            fetched_at=raw.fetched_at,
            language=source.language,
            region=source.region,
            asset_classes=source.asset_classes,
            title_hash=title_hash(title),
            canonical_url_hash=content_hash(canonical_url),
            normalized_text_hash=content_hash(f"{title} {snippet}"),
            processing_status="normalized",
        )
        session.add(item)
        inserted += 1
    return inserted
async def mark_exact_duplicates(session: AsyncSession) -> int:
    stmt = select(NormalizedNewsItem).where(NormalizedNewsItem.processing_status == "normalized")
    items = list((await session.scalars(stmt)).all())
    seen: set[tuple[str | None, str]] = set()
    duplicates = 0
    for item in items:
        key = (item.canonical_url_hash, item.title_hash)
        if key in seen:
            item.processing_status = "deduped"
            duplicates += 1
        else:
            seen.add(key)
    return duplicates
