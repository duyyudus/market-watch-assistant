from __future__ import annotations

from typing import Annotated

import typer
from sqlalchemy import func, or_, select

from bot_worker.cli.apps import embedding_app
from bot_worker.cli.common import _echo_json, _run, _settings, _with_session
from bot_worker.db.models import (
    EventCluster,
    EventClusterEmbedding,
    NewsItemEmbedding,
    NormalizedNewsItem,
)
from bot_worker.embeddings import EmbeddingConfig
from bot_worker.services import (
    embed_pending_event_clusters,
    embed_pending_news_items,
)


@embedding_app.command("backfill")
def embedding_backfill(
    kind: Annotated[str, typer.Option("--kind")] = "news",
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
) -> None:
    """Backfill vector embeddings for pending news items or event clusters."""
    settings = _settings()
    config = EmbeddingConfig.from_settings(settings)

    async def action(session):
        if kind == "news":
            count = await embed_pending_news_items(session, config=config, limit=limit)
        elif kind == "events":
            count = await embed_pending_event_clusters(session, config=config, limit=limit)
        else:
            typer.echo("kind must be news or events")
            raise typer.Exit(1)
        _echo_json({"kind": kind, "embedded": count, "provider": config.provider})

    _run(_with_session(action))


@embedding_app.command("status")
def embedding_status() -> None:
    """Show embedding coverage for news items and event clusters."""
    async def action(session):
        news_items = await session.scalar(select(func.count()).select_from(NormalizedNewsItem))
        news_embeddings = await session.scalar(select(func.count()).select_from(NewsItemEmbedding))
        event_clusters = await session.scalar(select(func.count()).select_from(EventCluster))
        event_embeddings = await session.scalar(
            select(func.count()).select_from(EventClusterEmbedding)
        )
        _echo_json(
            {
                "news_items": news_items or 0,
                "news_embeddings": news_embeddings or 0,
                "news_pending": max(0, (news_items or 0) - (news_embeddings or 0)),
                "event_clusters": event_clusters or 0,
                "event_embeddings": event_embeddings or 0,
                "event_pending": max(0, (event_clusters or 0) - (event_embeddings or 0)),
            }
        )

    _run(_with_session(action))


@embedding_app.command("search")
def embedding_search(
    query: str,
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 20,
) -> None:
    """Search embeddable records by text metadata."""
    async def action(session):
        pattern = f"%{query}%"
        news_rows = list(
            (
                await session.scalars(
                    select(NormalizedNewsItem)
                    .where(
                        or_(
                            NormalizedNewsItem.title.ilike(pattern),
                            NormalizedNewsItem.snippet.ilike(pattern),
                        )
                    )
                    .order_by(NormalizedNewsItem.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )
        event_rows = list(
            (
                await session.scalars(
                    select(EventCluster)
                    .where(
                        or_(
                            EventCluster.canonical_headline.ilike(pattern),
                            EventCluster.summary.ilike(pattern),
                        )
                    )
                    .order_by(EventCluster.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )
        _echo_json(
            {
                "news": [
                    {"id": item.id, "title": item.title, "source_name": item.source_name}
                    for item in news_rows
                ],
                "events": [
                    {
                        "id": event.id,
                        "headline": event.canonical_headline,
                        "final_score": event.final_score,
                    }
                    for event in event_rows
                ],
            }
        )

    _run(_with_session(action))
