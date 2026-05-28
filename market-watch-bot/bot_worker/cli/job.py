from __future__ import annotations

from typing import Annotated

import typer
from sqlalchemy import select

from bot_worker.cli.apps import job_app
from bot_worker.cli.common import _run, _with_session
from bot_worker.db.models import JobRun
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
    if name in CORE_JOBS:
        typer.echo(
            f"No direct runner is implemented for job {name}; use `pipeline run` "
            "or `worker start` for staged pipeline execution."
        )
        raise typer.Exit(1)
    typer.echo(f"Unknown job {name}. Run `market-watch job list` to see registered jobs.")
    raise typer.Exit(1)
@job_app.command("history")
def job_history(
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 20,
    name: Annotated[str | None, typer.Option("--name")] = None,
) -> None:
    """View recent scheduler job execution history."""
    async def action(session):
        stmt = select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
        if name:
            stmt = stmt.where(JobRun.job_name == name)
        rows = list((await session.execute(stmt)).scalars().all())
        if not rows:
            typer.echo("No job runs found")
            return
        for run in rows:
            typer.echo(
                f"{run.id}\t{run.job_name}\t{run.status}\t"
                f"{run.started_at}\t{run.completed_at or '-'}\t{run.error_message or '-'}"
            )

    _run(_with_session(action))


@job_app.command("failures")
def job_failures(limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 20) -> None:
    """List failed job executions."""
    async def action(session):
        rows = list(
            (
                await session.execute(
                    select(JobRun)
                    .where(JobRun.status != "success")
                    .order_by(JobRun.started_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            typer.echo("No failed job runs found")
            return
        for run in rows:
            typer.echo(
                f"{run.id}\t{run.job_name}\t{run.status}\t"
                f"{run.started_at}\t{run.error_message or '-'}"
            )

    _run(_with_session(action))
