from __future__ import annotations

from typing import Annotated

import typer

from bot_worker.cli.apps import embedding_app
from bot_worker.cli.common import _echo_json, _run, _settings, _with_session
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
