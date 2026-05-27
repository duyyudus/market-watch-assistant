from __future__ import annotations

from typing import Annotated

import typer

from bot_worker.cli.apps import job_app
from bot_worker.services import (
    CORE_JOBS,
)


@job_app.command("list")
def job_list() -> None:
    """List all core scheduler jobs."""
    for job in CORE_JOBS:
        typer.echo(job)
@job_app.command("run")
def job_run(name: str, dry_run: Annotated[bool, typer.Option("--dry-run")] = False) -> None:
    """Run a specific background job immediately."""
    if name == "pipeline":
        from bot_worker.cli.pipeline import pipeline_run

        pipeline_run(dry_run=dry_run)
        return
    if name == "retention_cleanup":
        from bot_worker.cli.retention import retention_run

        retention_run()
        return
    typer.echo(f"Job {name} is registered; direct implementation is deferred in MVP")
@job_app.command("history")
def job_history() -> None:
    """View the execution history of scheduler jobs (MVP placeholder)."""
    typer.echo(
        "job history is stored in job_runs; use database queries for detailed MVP inspection"
    )
@job_app.command("failures")
def job_failures() -> None:
    """List or inspect failed job executions (MVP placeholder)."""
    typer.echo("failed job retry queue is deferred in MVP")
