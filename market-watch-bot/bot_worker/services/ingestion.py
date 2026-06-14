from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, func, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import (
    NewsSource,
    NormalizedNewsItem,
    RawNewsItem,
)
from bot_worker.normalize import (
    canonicalize_url,
    content_hash,
    is_disclosure_noise_title,
    normalize_datetime,
    normalize_text,
    title_hash,
)
from bot_worker.rss import ParsedFeedItem
from bot_worker.services.common import _json_safe, _published_to_string
from bot_worker.services.sources import effective_source_score


@dataclass(frozen=True)
class _NormalizedCandidate:
    raw: RawNewsItem
    source: NewsSource
    title: str
    published_at: datetime | None
    snippet: str
    raw_content: str
    canonical_url: str
    title_hash: str
    canonical_url_hash: str
    normalized_text_hash: str


def _dedup_key(
    *,
    source_type: str,
    snippet: str | None,
    canonical_url_hash: str | None,
    title_hash: str,
    normalized_text_hash: str,
) -> tuple[str, str, str]:
    if source_type == "google-rss" and snippet:
        return ("google-rss-snippet", normalized_text_hash, title_hash)
    return ("url", canonical_url_hash or "", "")


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
    session: AsyncSession,
    *,
    limit: int = 500,
    freshness_hours: int = 72,
    tracking_params: list[str] | set[str] | None = None,
    disclosure_noise_patterns: list[str] | None = None,
) -> int:
    stmt = (
        select(RawNewsItem, NewsSource)
        .join(NewsSource, NewsSource.id == RawNewsItem.source_id)
        .outerjoin(NormalizedNewsItem, NormalizedNewsItem.raw_item_id == RawNewsItem.id)
        .where(NormalizedNewsItem.id.is_(None))
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    now = datetime.now(UTC)

    candidates: list[_NormalizedCandidate] = []
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
        raw_content = normalize_text(raw.raw_content)
        canonical_url = canonicalize_url(
            raw.raw_url,
            tracking_params=set(tracking_params) if tracking_params is not None else None,
        )
        item_title_hash = title_hash(title)
        canonical_url_hash = content_hash(canonical_url)
        normalized_text_hash = content_hash(f"{title} {snippet} {raw_content}")
        candidates.append(
            _NormalizedCandidate(
                raw=raw,
                source=source,
                title=title,
                published_at=published_at,
                snippet=snippet,
                raw_content=raw_content,
                canonical_url=canonical_url,
                title_hash=item_title_hash,
                canonical_url_hash=canonical_url_hash,
                normalized_text_hash=normalized_text_hash,
            )
        )

    existing_keys: set[tuple[str, str, str]] = set()
    if candidates:
        canonical_url_hashes = {candidate.canonical_url_hash for candidate in candidates}
        normalized_text_hashes = {candidate.normalized_text_hash for candidate in candidates}
        existing_rows = (
            await session.execute(
                select(
                    NormalizedNewsItem.source_type,
                    NormalizedNewsItem.snippet,
                    NormalizedNewsItem.canonical_url_hash,
                    NormalizedNewsItem.title_hash,
                    NormalizedNewsItem.normalized_text_hash,
                )
                .where(NormalizedNewsItem.processing_status == "normalized")
                .where(
                    (
                        NormalizedNewsItem.canonical_url_hash.in_(canonical_url_hashes)
                    )
                    | (NormalizedNewsItem.normalized_text_hash.in_(normalized_text_hashes))
                )
            )
        ).all()
        existing_keys = {
            _dedup_key(
                source_type=str(row[0]),
                snippet=str(row[1]) if row[1] is not None else None,
                canonical_url_hash=str(row[2]) if row[2] is not None else None,
                title_hash=str(row[3]),
                normalized_text_hash=str(row[4]),
            )
            for row in existing_rows
        }

    inserted = 0
    batch_active_keys: set[tuple[str, str, str]] = set()
    for candidate in candidates:
        key = _dedup_key(
            source_type=candidate.source.source_type,
            snippet=candidate.snippet,
            canonical_url_hash=candidate.canonical_url_hash,
            title_hash=candidate.title_hash,
            normalized_text_hash=candidate.normalized_text_hash,
        )
        if is_disclosure_noise_title(candidate.title, disclosure_noise_patterns):
            # Routine NAV/disclosure boilerplate: keep the row for provenance but mark it
            # ignored so it never reaches clustering, embedding, or alerts.
            processing_status = "ignored"
        elif key in existing_keys or key in batch_active_keys:
            processing_status = "deduped"
        else:
            processing_status = "normalized"
        if processing_status == "normalized":
            batch_active_keys.add(key)

        item = NormalizedNewsItem(
            source_id=candidate.source.id,
            raw_item_id=candidate.raw.id,
            title=candidate.title,
            snippet=candidate.snippet or None,
            raw_content=candidate.raw_content or None,
            url=candidate.raw.raw_url,
            canonical_url=candidate.canonical_url,
            source_name=candidate.source.name,
            source_type=candidate.source.source_type,
            source_score=effective_source_score(candidate.source),
            published_at=candidate.published_at,
            fetched_at=candidate.raw.fetched_at,
            language=candidate.source.language,
            region=candidate.source.region,
            asset_classes=candidate.source.asset_classes,
            title_hash=candidate.title_hash,
            canonical_url_hash=candidate.canonical_url_hash,
            normalized_text_hash=candidate.normalized_text_hash,
            processing_status=processing_status,
            full_text_available=False,
            full_text_extraction_status=(
                "skipped" if candidate.source.source_type == "google-rss" else "pending"
            ),
            full_text_last_error=(
                "google_rss_feed_only"
                if candidate.source.source_type == "google-rss"
                else None
            ),
        )
        session.add(item)
        inserted += 1
    return inserted
async def mark_exact_duplicates(session: AsyncSession) -> int:
    google_rss_with_snippet = and_(
        NormalizedNewsItem.source_type == "google-rss",
        NormalizedNewsItem.snippet.is_not(None),
    )
    ranked = (
        select(
            NormalizedNewsItem.id.label("news_id"),
            func.row_number()
            .over(
                partition_by=(
                    case(
                        (google_rss_with_snippet, literal("google-rss-snippet")),
                        else_=literal("url"),
                    ),
                    case(
                        (
                            google_rss_with_snippet,
                            NormalizedNewsItem.normalized_text_hash,
                        ),
                        else_=NormalizedNewsItem.canonical_url_hash,
                    ),
                    case(
                        (google_rss_with_snippet, NormalizedNewsItem.title_hash),
                        else_=literal(""),
                    ),
                ),
                order_by=(
                    NormalizedNewsItem.created_at.asc(),
                    NormalizedNewsItem.id.asc(),
                ),
            )
            .label("row_number"),
        )
        .where(NormalizedNewsItem.processing_status == "normalized")
        .subquery()
    )
    duplicate_ids = select(ranked.c.news_id).where(ranked.c.row_number > 1)
    result = await session.execute(
        update(NormalizedNewsItem)
        .where(NormalizedNewsItem.id.in_(duplicate_ids))
        .values(processing_status="deduped")
    )
    return int(result.rowcount or 0)
