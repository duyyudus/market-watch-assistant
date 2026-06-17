from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import text

from bot_worker.cli.apps import app
from bot_worker.cli.common import _db_error, _run, _settings, _with_session
from bot_worker.config import write_default_files
from bot_worker.db.session import make_engine
from bot_worker.services import (
    seed_configuration_presets,
    seed_starter_sources,
)


@app.callback()
def main() -> None:
    """Initialize logging for CLI commands."""
    from bot_worker.logging import setup_logging
    setup_logging(_settings(), component="cli")
@app.command()
def init(
    project_dir: Annotated[Path, typer.Option(help="Directory for runtime files")] = Path("."),
) -> None:
    """Create default .env, .env.example, settings.yml, and starter source YAML."""
    write_default_files(project_dir)
    typer.echo(f"Initialized market-watch-bot files in {project_dir}")
@app.command()
def migrate() -> None:
    """Run Alembic migrations against DATABASE_URL."""
    result = subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=False)
    if result.returncode == 0:
        async def action(session):
            added = await seed_starter_sources(session)
            presets_changed = await seed_configuration_presets(session, _settings())
            typer.echo(f"Seeded {added} starter sources")
            typer.echo(
                "Seeded configuration presets"
                if presets_changed
                else "Configuration presets already current"
            )

        try:
            _run(_with_session(action))
        except Exception as exc:  # noqa: BLE001
            _db_error(exc)
            raise typer.Exit(1) from exc
    raise typer.Exit(result.returncode)
@app.command()
def doctor() -> None:
    """Check configuration, database connectivity, and pgvector availability."""
    settings = _settings()
    typer.echo(f"app: {settings.app.name}")
    typer.echo(f"environment: {settings.app.environment}")
    typer.echo(f"database_url: {settings.database_url}")

    async def check() -> None:
        engine = make_engine(settings)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                vector = await conn.scalar(
                    text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
                )
                typer.echo("database reachable: yes")
                typer.echo(f"pgvector installed: {'yes' if vector else 'no'}")
        finally:
            await engine.dispose()

    try:
        _run(check())
    except Exception as exc:  # noqa: BLE001 - doctor reports environment diagnostics
        _db_error(exc)
    typer.echo(f"openrouter configured: {'yes' if settings.openrouter_api_key else 'no'}")
    typer.echo(f"alert channel: {settings.alerts.default_channel}")
