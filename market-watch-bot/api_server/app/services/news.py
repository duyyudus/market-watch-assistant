from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api_server.app.schemas import EntityRead, NewsRead
from api_server.app.services.query import apply_pagination, count_for
from common.db.models import EventClusterItem, NewsEntity, NormalizedNewsItem


async def list_news(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    status_filter: str | None,
    domain: str | None,
    source_id: str | None,
    region: str | None,
    q: str | None,
) -> tuple[list[NormalizedNewsItem], int]:
    stmt = select(NormalizedNewsItem).order_by(NormalizedNewsItem.created_at.desc())
    if status_filter:
        stmt = stmt.where(NormalizedNewsItem.processing_status == status_filter)
    if source_id:
        stmt = stmt.where(NormalizedNewsItem.source_id == source_id)
    if region:
        stmt = stmt.where(NormalizedNewsItem.region == region)
    if domain:
        normalized_domain = domain.lower().strip()
        canonical_url = func.lower(NormalizedNewsItem.canonical_url)
        url = func.lower(NormalizedNewsItem.url)
        domain_patterns = (
            f"http://{normalized_domain}",
            f"https://{normalized_domain}",
            f"http://{normalized_domain}/%",
            f"https://{normalized_domain}/%",
            f"http://{normalized_domain}:%",
            f"https://{normalized_domain}:%",
        )
        canonical_matches = or_(*(canonical_url.like(pattern) for pattern in domain_patterns))
        url_matches = or_(*(url.like(pattern) for pattern in domain_patterns))
        stmt = stmt.where(
            or_(
                and_(NormalizedNewsItem.canonical_url.is_not(None), canonical_matches),
                and_(NormalizedNewsItem.canonical_url.is_(None), url_matches),
            )
        )
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                NormalizedNewsItem.title.ilike(pattern),
                NormalizedNewsItem.snippet.ilike(pattern),
                NormalizedNewsItem.url.ilike(pattern),
            )
        )
    total = await count_for(session, stmt)
    rows = list((await session.scalars(apply_pagination(stmt, limit=limit, offset=offset))).all())
    return rows, total


async def list_news_filter_options(session: AsyncSession) -> dict[str, list[str]]:
    statuses = list(
        (
            await session.scalars(
                select(NormalizedNewsItem.processing_status)
                .where(NormalizedNewsItem.processing_status.is_not(None))
                .distinct()
                .order_by(NormalizedNewsItem.processing_status)
            )
        ).all()
    )
    regions = list(
        (
            await session.scalars(
                select(NormalizedNewsItem.region)
                .where(NormalizedNewsItem.region.is_not(None))
                .distinct()
                .order_by(NormalizedNewsItem.region)
            )
        ).all()
    )
    return {"statuses": statuses, "regions": regions}


async def list_news_domains(session: AsyncSession) -> list[str]:
    rows = list(
        (
            await session.execute(
                select(NormalizedNewsItem.canonical_url, NormalizedNewsItem.url)
            )
        ).all()
    )
    domains = {
        domain
        for canonical_url, url in rows
        if (domain := domain_for(canonical_url or url))
    }
    return sorted(domains)


async def get_news_detail(session: AsyncSession, item: NormalizedNewsItem) -> dict[str, object]:
    entities = list(
        (
            await session.scalars(
                select(NewsEntity)
                .where(NewsEntity.news_item_id == item.id)
                .order_by(NewsEntity.confidence.desc())
            )
        ).all()
    )
    clusters = list(
        (
            await session.scalars(
                select(EventClusterItem).where(EventClusterItem.news_item_id == item.id)
            )
        ).all()
    )
    return {
        **NewsRead.model_validate(item).model_dump(),
        "raw_content": item.raw_content,
        "full_text_extraction_status": item.full_text_extraction_status,
        "full_text_attempt_count": item.full_text_attempt_count,
        "full_text_last_attempted_at": item.full_text_last_attempted_at,
        "full_text_last_http_status": item.full_text_last_http_status,
        "full_text_last_error": item.full_text_last_error,
        "full_text_next_retry_at": item.full_text_next_retry_at,
        "entities": [EntityRead.model_validate(entity).model_dump() for entity in entities],
        "clusters": [
            {
                "event_cluster_id": row.event_cluster_id,
                "relation_type": row.relation_type,
                "similarity_score": row.similarity_score,
                "decision_metadata": row.decision_metadata,
                "added_at": row.added_at,
            }
            for row in clusters
        ],
    }


def domain_for(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    return parsed.hostname or None
