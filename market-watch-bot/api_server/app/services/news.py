from __future__ import annotations

from sqlalchemy import or_, select
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
    q: str | None,
) -> tuple[list[NormalizedNewsItem], int]:
    stmt = select(NormalizedNewsItem).order_by(NormalizedNewsItem.created_at.desc())
    if status_filter:
        stmt = stmt.where(NormalizedNewsItem.processing_status == status_filter)
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
        "entities": [EntityRead.model_validate(entity).model_dump() for entity in entities],
        "clusters": [
            {
                "event_cluster_id": row.event_cluster_id,
                "relation_type": row.relation_type,
                "similarity_score": row.similarity_score,
                "added_at": row.added_at,
            }
            for row in clusters
        ],
    }
