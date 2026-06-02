from __future__ import annotations

import subprocess

import typer

from bot_worker.cli.apps import retention_app
from bot_worker.cli.common import (
    _db_error,
    _echo_json,
    _run,
    _settings,
    _with_session,
)
from bot_worker.retention import RetentionPolicy
from bot_worker.services import (
    baseline_reset_preview,
    retention_preview,
    run_baseline_reset,
    run_retention,
    seed_configuration_presets,
    seed_starter_sources,
)


@retention_app.command("show")
def retention_show() -> None:
    """Display the active database retention policy configuration."""
    settings = _settings()
    _echo_json(settings.retention.model_dump())
@retention_app.command("preview")
def retention_preview_command() -> None:
    """Preview which database records would be cleaned up under the retention policy."""
    settings = _settings()
    policy = RetentionPolicy(**settings.retention.model_dump())

    async def action(session):
        _echo_json(await retention_preview(session, policy))

    _run(_with_session(action))
@retention_app.command("run")
def retention_run() -> None:
    """Execute retention cleanup to purge expired news, event, and run records."""
    settings = _settings()
    policy = RetentionPolicy(**settings.retention.model_dump())

    async def action(session):
        _echo_json(await run_retention(session, policy))

    _run(_with_session(action))


@retention_app.command("reset-baseline")
def retention_reset_baseline(
    yes: bool = typer.Option(False, "--yes", help="Confirm destructive baseline reset."),
) -> None:
    """Delete derived/runtime data while preserving baseline news and configuration."""

    async def action(session):
        if not yes:
            typer.echo("Refusing to reset baseline without --yes; preview follows:")
            _echo_json(await baseline_reset_preview(session))
            raise typer.Exit(1)
        _echo_json(await run_baseline_reset(session))

    _run(_with_session(action))


@retention_app.command("reset-all")
def retention_reset_all(
    yes: bool = typer.Option(False, "--yes", help="Confirm destructive database hard reset."),
) -> None:
    """Wipe everything in the database and re-seed defaults.

    Downgrades the database to base state, migrates to head, and seeds starter sources
    and configuration presets from local files.
    """
    if not yes:
        typer.echo("Refusing to reset all without --yes.")
        raise typer.Exit(1)

    typer.echo("Downgrading database schema to base...")
    result_down = subprocess.run(["uv", "run", "alembic", "downgrade", "base"], check=False)
    if result_down.returncode != 0:
        typer.echo("Database downgrade failed")
        raise typer.Exit(result_down.returncode)

    typer.echo("Upgrading database schema to head...")
    result_up = subprocess.run(["uv", "run", "alembic", "upgrade", "head"], check=False)
    if result_up.returncode != 0:
        typer.echo("Database upgrade failed")
        raise typer.Exit(result_up.returncode)

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
    typer.echo("Database reset completed successfully")

