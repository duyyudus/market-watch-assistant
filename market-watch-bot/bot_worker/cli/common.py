from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable

import typer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot_worker.config import Settings, load_settings
from bot_worker.db.session import make_session_factory


def _settings() -> Settings:
    return load_settings()

def _run(coro: Awaitable[object]) -> object:
    return asyncio.run(coro)

async def _with_session(
    fn: Callable,
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> object:
    settings = settings or _settings()
    factory = session_factory or make_session_factory(settings)
    async with factory() as session, session.begin():
        return await fn(session)

async def _record_failed_job(
    factory: async_sessionmaker[AsyncSession],
    job_name: str,
    exc: Exception,
) -> None:
    """Persist a failed JobRun in its own transaction so crashes are observable.

    The pipeline runs inside a single transaction that rolls back on failure, which
    otherwise leaves no DB trace that a run was even attempted.
    """
    from contextlib import suppress

    from bot_worker.services import record_job_run

    with suppress(Exception):
        async with factory() as session, session.begin():
            await record_job_run(
                session,
                job_name,
                {"error": str(exc)},
                status="failed",
                error_message=str(exc),
            )


def _echo_json(data: object) -> None:
    typer.echo(json.dumps(_redact_cli_secrets(data), indent=2, sort_keys=True, default=str))

def _db_error(exc: Exception) -> None:
    typer.echo(f"Database unavailable: {_redact_cli_secrets(str(exc))}")


def _redact_cli_secrets(value: object) -> object:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return value
    if isinstance(value, str):
        return value.replace(token, "[REDACTED_TELEGRAM_TOKEN]")
    if isinstance(value, list):
        return [_redact_cli_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_cli_secrets(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_cli_secrets(item) for key, item in value.items()}
    return value
