from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot_worker.db.models import EventCluster, EventClusterItem, NormalizedNewsItem


@dataclass(frozen=True)
class FullTextStats:
    attempted: int = 0
    extracted: int = 0
    failed: int = 0


def extract_article_text(html: str) -> str | None:
    try:
        import trafilatura  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - optional dependency fallback keeps tests lightweight
        trafilatura = None
    if trafilatura is not None:
        text = trafilatura.extract(html)
        if text:
            return text.strip()
    text = re.sub(r"<(script|style).*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


async def extract_full_text_for_priority_events(
    session: AsyncSession,
    *,
    threshold: int = 70,
    limit: int = 20,
) -> FullTextStats:
    stmt = (
        select(NormalizedNewsItem)
        .join(EventClusterItem, EventClusterItem.news_item_id == NormalizedNewsItem.id)
        .join(EventCluster, EventCluster.id == EventClusterItem.event_cluster_id)
        .where(NormalizedNewsItem.full_text_available.is_(False))
        .where((EventCluster.final_score >= threshold) | (EventCluster.source_count <= 1))
        .order_by(EventCluster.final_score.desc())
        .limit(limit)
    )
    items = list((await session.scalars(stmt)).all())
    attempted = extracted = failed = 0
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        for item in items:
            attempted += 1
            try:
                response = await client.get(item.url)
                response.raise_for_status()
                text = extract_article_text(response.text)
                if not text:
                    failed += 1
                    continue
            except Exception:  # noqa: BLE001 - extraction should not block pipeline
                failed += 1
                continue
            item.raw_content = text
            item.full_text_available = True
            extracted += 1
    return FullTextStats(attempted=attempted, extracted=extracted, failed=failed)
