from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import NewsSource, NormalizedNewsItem
from common.article_fallbacks import first_article_fallback_text
from common.article_text import extract_article_text
from common.source_policies import article_fetch_headers


@dataclass(frozen=True)
class FullTextStats:
    attempted: int = 0
    extracted: int = 0
    fallback_used: int = 0
    skipped: int = 0
    retryable_failed: int = 0
    failed: int = 0


TERMINAL_HTTP_STATUSES = {401, 403, 404, 410}
RETRYABLE_HTTP_STATUSES = {408, 429, 500, 502, 503, 504}
SOURCE_EXTRACTION_LIMITED_MIN_FAILURES = 3
SOURCE_EXTRACTION_LIMITED_COOLDOWN = timedelta(days=7)


async def extract_full_text_for_pending_items(
    session: AsyncSession,
    *,
    limit: int | None = None,
    max_concurrency: int = 8,
    domain_request_interval_seconds: float = 1.5,
) -> FullTextStats:
    stmt = build_full_text_backlog_stmt(limit=limit)
    items = list((await session.scalars(stmt)).all())
    source_stats: dict[str, dict[str, int]] = {}
    sources: dict[str, NewsSource | None] = {}
    source_ids = {item.source_id for item in items}
    if source_ids:
        db_sources = list(
            (await session.scalars(select(NewsSource).where(NewsSource.id.in_(source_ids)))).all()
        )
        sources.update({source.id: source for source in db_sources})
        for source_id in source_ids:
            sources.setdefault(source_id, None)
    semaphore = asyncio.Semaphore(max(1, max_concurrency))
    domain_semaphores: dict[str, asyncio.Semaphore] = {}
    domain_cooldowns: dict[str, datetime] = {}
    domain_next_request_at: dict[str, float] = {}

    async def extract_with_limit(
        client: httpx.AsyncClient,
        item: NormalizedNewsItem,
    ) -> FullTextStats:
        domain = _article_domain(item.url)
        domain_semaphore = domain_semaphores.setdefault(domain, asyncio.Semaphore(1))
        async with semaphore, domain_semaphore:
            if _domain_rate_limited(domain_cooldowns, domain):
                source_stats.setdefault(
                    item.source_id,
                    _empty_source_full_text_stats(),
                )["retryable_failed"] += 1
                _mark_retry_until(
                    item,
                    reason="source_rate_limited",
                    retry_at=domain_cooldowns[domain],
                )
                return FullTextStats(retryable_failed=1, failed=1)
            loop = asyncio.get_running_loop()
            next_request_at = domain_next_request_at.get(domain)
            if next_request_at is not None:
                wait_seconds = next_request_at - loop.time()
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
            result = await _extract_one_item(
                client=client,
                item=item,
                sources=sources,
                source_stats=source_stats,
            )
            if domain_request_interval_seconds > 0:
                domain_next_request_at[domain] = (
                    asyncio.get_running_loop().time() + domain_request_interval_seconds
                )
            if (
                item.full_text_last_http_status == 429
                and item.full_text_extraction_status == "retry"
                and item.full_text_next_retry_at is not None
            ):
                domain_cooldowns[domain] = item.full_text_next_retry_at
            return result

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        results = await asyncio.gather(*[extract_with_limit(client, item) for item in items])
    await _update_source_quality_metrics(session, sources, source_stats)
    return FullTextStats(
        attempted=sum(result.attempted for result in results),
        extracted=sum(result.extracted for result in results),
        fallback_used=sum(result.fallback_used for result in results),
        skipped=sum(result.skipped for result in results),
        retryable_failed=sum(result.retryable_failed for result in results),
        failed=sum(result.failed for result in results),
    )


def build_full_text_backlog_stmt(
    *,
    limit: int | None = None,
):
    stmt = (
        select(NormalizedNewsItem)
        .where(NormalizedNewsItem.processing_status == "normalized")
        .where(NormalizedNewsItem.full_text_available.is_(False))
        .where(NormalizedNewsItem.source_type != "google-rss")
        .where(
            or_(
                NormalizedNewsItem.full_text_extraction_status == "pending",
                NormalizedNewsItem.full_text_extraction_status == "retry",
            )
        )
        .where(
            or_(
                NormalizedNewsItem.full_text_next_retry_at.is_(None),
                NormalizedNewsItem.full_text_next_retry_at <= datetime.now(UTC),
            )
        )
        .order_by(NormalizedNewsItem.created_at.desc(), NormalizedNewsItem.id.asc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return stmt


def _article_domain(url: str) -> str:
    return urlsplit(url).netloc.lower()


def _domain_rate_limited(domain_cooldowns: dict[str, datetime], domain: str) -> bool:
    retry_at = domain_cooldowns.get(domain)
    return retry_at is not None and retry_at > datetime.now(UTC)


async def extract_full_text_for_priority_events(
    session: AsyncSession,
    *,
    threshold: int = 70,
    single_source_threshold: int = 80,
    lookback_days: int = 7,
    limit: int = 20,
    per_source_limit: int = 2,
) -> FullTextStats:
    return await extract_full_text_for_pending_items(session, limit=limit)


def build_full_text_priority_stmt(
    *,
    threshold: int = 70,
    single_source_threshold: int = 80,
    lookback_days: int = 7,
    limit: int = 100,
):
    return build_full_text_backlog_stmt(limit=limit)


async def _extract_one_item(
    *,
    client: httpx.AsyncClient,
    item: NormalizedNewsItem,
    sources: dict[str, NewsSource | None],
    source_stats: dict[str, dict[str, int]],
) -> FullTextStats:
    source = sources.get(item.source_id)
    stats = source_stats.setdefault(item.source_id, _empty_source_full_text_stats())
    if item.source_type == "google-rss" or getattr(source, "source_type", None) == "google-rss":
        stats["skipped"] += 1
        _mark_skipped(item, reason="google_rss_feed_only")
        return FullTextStats(skipped=1)
    if _source_extraction_limited(source):
        stats["attempted"] += 1
        _mark_attempt(item)
        if _use_fallback(item, reason="source_extraction_limited"):
            stats["fallback_used"] += 1
            return FullTextStats(attempted=1, fallback_used=1)
        stats["skipped"] += 1
        _mark_skipped(item, reason="source_extraction_limited")
        return FullTextStats(attempted=1, skipped=1)

    stats["attempted"] += 1
    _mark_attempt(item)
    try:
        response = await client.get(item.url, headers=article_fetch_headers())
        item.full_text_last_http_status = response.status_code
        if response.status_code in TERMINAL_HTTP_STATUSES:
            stats["terminal_failures"] += 1
            if _use_fallback(item, reason=f"http_{response.status_code}"):
                stats["fallback_used"] += 1
                return FullTextStats(attempted=1, fallback_used=1)
            stats["skipped"] += 1
            _mark_skipped(item, reason=f"http_{response.status_code}")
            return FullTextStats(attempted=1, skipped=1)
        if response.status_code in RETRYABLE_HTTP_STATUSES or response.status_code >= 500:
            stats["retryable_failed"] += 1
            _mark_retry(
                item,
                reason=f"http_{response.status_code}",
                retry_after=response.headers.get("Retry-After"),
            )
            return FullTextStats(attempted=1, retryable_failed=1, failed=1)
        response.raise_for_status()
        text = extract_article_text(response.text, url=item.url)
        if not text:
            stats["terminal_failures"] += 1
            if _use_fallback(item, reason="no_text_extracted"):
                stats["fallback_used"] += 1
                return FullTextStats(attempted=1, fallback_used=1)
            stats["skipped"] += 1
            _mark_skipped(item, reason="no_text_extracted")
            return FullTextStats(attempted=1, skipped=1)
    except Exception:  # noqa: BLE001 - extraction should not block pipeline
        stats["retryable_failed"] += 1
        _mark_retry(item, reason="request_failed")
        return FullTextStats(attempted=1, retryable_failed=1, failed=1)
    item.raw_content = text
    item.full_text_available = True
    item.full_text_extraction_status = "extracted"
    item.full_text_last_error = None
    item.full_text_next_retry_at = None
    stats["extracted"] += 1
    return FullTextStats(attempted=1, extracted=1)


def _mark_attempt(item: NormalizedNewsItem) -> None:
    item.full_text_attempt_count = int(item.full_text_attempt_count or 0) + 1
    item.full_text_last_attempted_at = datetime.now(UTC)


def _use_fallback(item: NormalizedNewsItem, *, reason: str) -> bool:
    fallback = first_article_fallback_text(item.raw_content, item.snippet, item.title)
    if not fallback:
        return False
    item.raw_content = fallback
    item.full_text_available = True
    item.full_text_extraction_status = "fallback"
    item.full_text_last_error = reason
    item.full_text_next_retry_at = None
    return True


def _mark_skipped(item: NormalizedNewsItem, *, reason: str) -> None:
    item.full_text_extraction_status = "skipped"
    item.full_text_last_error = reason
    item.full_text_next_retry_at = None


def _mark_retry(item: NormalizedNewsItem, *, reason: str, retry_after: str | None = None) -> None:
    item.full_text_extraction_status = "retry"
    item.full_text_last_error = reason
    item.full_text_next_retry_at = datetime.now(UTC) + _retry_backoff(
        item.full_text_attempt_count,
        retry_after=retry_after,
    )


def _mark_retry_until(item: NormalizedNewsItem, *, reason: str, retry_at: datetime) -> None:
    item.full_text_extraction_status = "retry"
    item.full_text_last_error = reason
    item.full_text_last_http_status = None
    item.full_text_next_retry_at = retry_at


def _retry_backoff(attempt_count: int | None, *, retry_after: str | None = None) -> timedelta:
    parsed_retry_after = _parse_retry_after(retry_after)
    if parsed_retry_after is not None:
        return parsed_retry_after
    attempts = max(1, int(attempt_count or 1))
    minutes = min(24 * 60, 15 * (2 ** (attempts - 1)))
    return timedelta(minutes=minutes)


def _parse_retry_after(value: str | None) -> timedelta | None:
    if not value:
        return None
    try:
        seconds = int(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(retry_at - datetime.now(UTC), timedelta())
    return max(timedelta(seconds=seconds), timedelta())


def _empty_source_full_text_stats() -> dict[str, int]:
    return {
        "attempted": 0,
        "extracted": 0,
        "fallback_used": 0,
        "skipped": 0,
        "terminal_failures": 0,
        "retryable_failed": 0,
    }


def _source_extraction_limited(source: NewsSource | None) -> bool:
    if source is None or not isinstance(source.quality_metrics, dict):
        return False
    full_text = source.quality_metrics.get("full_text")
    if not isinstance(full_text, dict):
        return False
    limited_until = full_text.get("extraction_limited_until")
    if not isinstance(limited_until, str):
        return False
    try:
        parsed = datetime.fromisoformat(limited_until)
    except ValueError:
        return False
    return parsed > datetime.now(UTC)


async def _update_source_quality_metrics(
    session: AsyncSession,
    sources: dict[str, NewsSource | None],
    source_stats: dict[str, dict[str, int]],
) -> None:
    for source_id, stats in source_stats.items():
        source = sources.get(source_id)
        if source is None:
            continue
        metrics: dict[str, Any] = dict(source.quality_metrics or {})
        full_text = dict(metrics.get("full_text") or {})
        full_text.update(stats)
        if (
            stats["terminal_failures"] >= SOURCE_EXTRACTION_LIMITED_MIN_FAILURES
            and stats["extracted"] == 0
        ):
            full_text["extraction_limited"] = True
            full_text["extraction_limited_until"] = (
                datetime.now(UTC) + SOURCE_EXTRACTION_LIMITED_COOLDOWN
            ).isoformat()
        elif stats["extracted"]:
            full_text["extraction_limited"] = False
            full_text.pop("extraction_limited_until", None)
        metrics["full_text"] = full_text
        source.quality_metrics = metrics
