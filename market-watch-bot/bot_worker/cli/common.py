from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

import typer

from bot_worker.config import Settings, load_settings
from bot_worker.db.session import make_session_factory


def _settings() -> Settings:
    return load_settings()

def _run(coro: Awaitable[object]) -> object:
    return asyncio.run(coro)

async def _with_session(fn: Callable) -> object:
    settings = _settings()
    factory = make_session_factory(settings)
    async with factory() as session, session.begin():
        return await fn(session)

def _echo_json(data: object) -> None:
    typer.echo(json.dumps(data, indent=2, sort_keys=True, default=str))

def _db_error(exc: Exception) -> None:
    typer.echo(f"Database unavailable: {exc}")

