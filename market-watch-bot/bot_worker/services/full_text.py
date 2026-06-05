from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import EventCluster, EventClusterItem, NewsSource, NormalizedNewsItem
from common.article_text import extract_article_text


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


async def extract_full_text_for_priority_events(
    session: AsyncSession,
    *,
    threshold: int = 70,
    single_source_threshold: int = 80,
    lookback_days: int = 7,
    limit: int = 20,
    per_source_limit: int = 2,
) -> FullTextStats:
    stmt = build_full_text_priority_stmt(
        threshold=threshold,
        single_source_threshold=single_source_threshold,
        lookback_days=lookback_days,
        limit=max(limit * 5, per_source_limit * 10),
    )
    candidates = list((await session.scalars(stmt)).all())
    items = _select_per_source(candidates, limit=limit, per_source_limit=per_source_limit)
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
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        results = await asyncio.gather(
            *[
                _extract_one_item(
                    client=client,
                    item=item,
                    sources=sources,
                    source_stats=source_stats,
                )
                for item in items
            ]
        )
    await _update_source_quality_metrics(session, sources, source_stats)
    return FullTextStats(
        attempted=sum(result.attempted for result in results),
        extracted=sum(result.extracted for result in results),
        fallback_used=sum(result.fallback_used for result in results),
        skipped=sum(result.skipped for result in results),
        retryable_failed=sum(result.retryable_failed for result in results),
        failed=sum(result.failed for result in results),
    )


def build_full_text_priority_stmt(
    *,
    threshold: int = 70,
    single_source_threshold: int = 80,
    lookback_days: int = 7,
    limit: int = 100,
):
    return (
        select(NormalizedNewsItem)
        .join(EventClusterItem, EventClusterItem.news_item_id == NormalizedNewsItem.id)
        .join(EventCluster, EventCluster.id == EventClusterItem.event_cluster_id)
        .where(NormalizedNewsItem.full_text_available.is_(False))
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
        .where(NormalizedNewsItem.created_at >= datetime.now(UTC) - timedelta(days=lookback_days))
        .where(
            or_(
                (EventCluster.source_count > 1) & (EventCluster.final_score >= threshold),
                (EventCluster.source_count <= 1)
                & (EventCluster.final_score >= single_source_threshold),
            )
        )
        .order_by(EventCluster.final_score.desc())
        .limit(limit)
    )


def _select_per_source(
    items: list[NormalizedNewsItem],
    *,
    limit: int,
    per_source_limit: int,
) -> list[NormalizedNewsItem]:
    selected: list[NormalizedNewsItem] = []
    counts: dict[str, int] = {}
    for item in items:
        if len(selected) >= limit:
            break
        count = counts.get(item.source_id, 0)
        if count >= per_source_limit:
            continue
        selected.append(item)
        counts[item.source_id] = count + 1
    return selected


async def _extract_one_item(
    *,
    client: httpx.AsyncClient,
    item: NormalizedNewsItem,
    sources: dict[str, NewsSource | None],
    source_stats: dict[str, dict[str, int]],
) -> FullTextStats:
    source = sources.get(item.source_id)
    stats = source_stats.setdefault(item.source_id, _empty_source_full_text_stats())
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
        response = await client.get(item.url)
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
            _mark_retry(item, reason=f"http_{response.status_code}")
            return FullTextStats(attempted=1, retryable_failed=1, failed=1)
        response.raise_for_status()
        text = extract_article_text(response.text)
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
    fallback = (item.raw_content or item.snippet or "").strip()
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


def _mark_retry(item: NormalizedNewsItem, *, reason: str) -> None:
    item.full_text_extraction_status = "retry"
    item.full_text_last_error = reason
    item.full_text_next_retry_at = datetime.now(UTC) + _retry_backoff(item.full_text_attempt_count)


def _retry_backoff(attempt_count: int | None) -> timedelta:
    attempts = max(1, int(attempt_count or 1))
    minutes = min(24 * 60, 15 * (2 ** (attempts - 1)))
    return timedelta(minutes=minutes)


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
