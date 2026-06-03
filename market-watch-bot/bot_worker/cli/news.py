from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer
from sqlalchemy import or_, select

from bot_worker.cli.apps import news_app
from bot_worker.cli.common import _echo_json, _run, _with_session
from bot_worker.db.models import (
    EventClusterItem,
    NewsEntity,
    NewsItemEmbedding,
    NormalizedNewsItem,
)


def _since_cutoff(value: str) -> datetime:
    now = datetime.now(UTC)
    stripped = value.strip().lower()
    if stripped.endswith("d") and stripped[:-1].isdigit():
        return now - timedelta(days=int(stripped[:-1]))
    if stripped.endswith("h") and stripped[:-1].isdigit():
        return now - timedelta(hours=int(stripped[:-1]))
    return datetime.fromisoformat(value).astimezone(UTC)


def _entity_payload(entity: NewsEntity) -> dict[str, object]:
    return {
        "id": entity.id,
        "entity_type": entity.entity_type,
        "raw_text": entity.raw_text,
        "normalized_name": entity.normalized_name,
        "ticker": entity.ticker,
        "exchange": entity.exchange,
        "country": entity.country,
        "confidence": entity.confidence,
    }


def _cluster_item_payload(item: EventClusterItem) -> dict[str, object]:
    return {
        "event_cluster_id": item.event_cluster_id,
        "news_item_id": item.news_item_id,
        "relation_type": item.relation_type,
        "similarity_score": item.similarity_score,
        "decision_metadata": item.decision_metadata,
        "added_at": item.added_at,
    }


@news_app.command("list")
def news_list(
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 20,
    since: Annotated[str | None, typer.Option("--since")] = None,
    status: Annotated[str | None, typer.Option("--status")] = None,
) -> None:
    """List ingested normalized news items."""
    async def action(session):
        stmt = (
            select(NormalizedNewsItem)
            .order_by(NormalizedNewsItem.created_at.desc())
            .limit(limit)
        )
        if since:
            stmt = stmt.where(NormalizedNewsItem.created_at >= _since_cutoff(since))
        if status:
            stmt = stmt.where(NormalizedNewsItem.processing_status == status)
        rows = list((await session.scalars(stmt)).all())
        if not rows:
            typer.echo("No news items found")
            return
        for item in rows:
            typer.echo(
                f"{item.id}\t{item.processing_status}\t{item.source_name}\t"
                f"{item.published_at or item.fetched_at}\t{item.title}"
            )

    _run(_with_session(action))


@news_app.command("show")
def news_show(identifier: str) -> None:
    """Display details of a specific normalized news item."""
    async def action(session):
        item = await session.get(NormalizedNewsItem, identifier)
        if item is None:
            typer.echo("News item not found")
            raise typer.Exit(1)
        entities = list(
            (
                await session.scalars(
                    select(NewsEntity)
                    .where(NewsEntity.news_item_id == item.id)
                    .order_by(NewsEntity.confidence.desc())
                )
            ).all()
        )
        cluster_items = list(
            (
                await session.scalars(
                    select(EventClusterItem).where(EventClusterItem.news_item_id == item.id)
                )
            ).all()
        )
        embedding = await session.scalar(
            select(NewsItemEmbedding).where(NewsItemEmbedding.news_item_id == item.id)
        )
        _echo_json(
            {
                "id": item.id,
                "raw_item_id": item.raw_item_id,
                "title": item.title,
                "snippet": item.snippet,
                "url": item.url,
                "canonical_url": item.canonical_url,
                "source": {
                    "id": item.source_id,
                    "name": item.source_name,
                    "type": item.source_type,
                    "score": item.source_score,
                },
                "published_at": item.published_at,
                "fetched_at": item.fetched_at,
                "language": item.language,
                "region": item.region,
                "asset_classes": item.asset_classes,
                "processing_status": item.processing_status,
                "is_paywalled": item.is_paywalled,
                "full_text_available": item.full_text_available,
                "entities": [_entity_payload(entity) for entity in entities],
                "clusters": [_cluster_item_payload(cluster) for cluster in cluster_items],
                "embedding": (
                    {
                        "provider": embedding.provider,
                        "model": embedding.embedding_model,
                        "version": embedding.embedding_version,
                        "dimensions": embedding.dimensions,
                        "created_at": embedding.created_at,
                    }
                    if embedding is not None
                    else None
                ),
            }
        )

    _run(_with_session(action))


@news_app.command("search")
def news_search(
    query: str,
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 20,
) -> None:
    """Search across ingested news items by title, snippet, or URL."""
    async def action(session):
        pattern = f"%{query}%"
        rows = list(
            (
                await session.scalars(
                    select(NormalizedNewsItem)
                    .where(
                        or_(
                            NormalizedNewsItem.title.ilike(pattern),
                            NormalizedNewsItem.snippet.ilike(pattern),
                            NormalizedNewsItem.url.ilike(pattern),
                        )
                    )
                    .order_by(NormalizedNewsItem.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )
        if not rows:
            typer.echo("No matching news items found")
            return
        for item in rows:
            typer.echo(f"{item.id}\t{item.source_name}\t{item.title}")

    _run(_with_session(action))


@news_app.command("entities")
def news_entities(identifier: str) -> None:
    """List extracted entities for a normalized news item."""
    async def action(session):
        rows = list(
            (
                await session.scalars(
                    select(NewsEntity)
                    .where(NewsEntity.news_item_id == identifier)
                    .order_by(NewsEntity.confidence.desc())
                )
            ).all()
        )
        _echo_json([_entity_payload(entity) for entity in rows])

    _run(_with_session(action))
