from __future__ import annotations

# Import modules for Typer command registration side effects.
from bot_worker.cli import (  # noqa: F401
    alerts,
    catalysts,
    core,
    digests,
    embeddings,
    events,
    health,
    job,
    llm,
    market,
    news,
    pipeline,
    retention,
    source,
    watchlist,
    worker,
)
from bot_worker.cli.apps import app

__all__ = ["app"]
