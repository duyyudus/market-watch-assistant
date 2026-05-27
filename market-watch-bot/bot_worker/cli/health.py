from __future__ import annotations

from datetime import UTC, datetime

import typer

from bot_worker.cli.apps import health_app
from bot_worker.cli.common import _settings
from bot_worker.retention import RetentionPolicy, retention_cutoffs
from bot_worker.services import (
    CORE_JOBS,
)


@health_app.command("sources")
def health_sources() -> None:
    """Check data ingestion source health and configuration."""
    from bot_worker.cli.source import source_list

    source_list()
@health_app.command("jobs")
def health_jobs() -> None:
    """Check the status and availability of core pipeline jobs."""
    from bot_worker.cli.job import job_list

    job_list()
@health_app.command("db")
def health_db() -> None:
    """Verify database connectivity, migrations, and extension compatibility."""
    from bot_worker.cli.core import doctor

    doctor()
@health_app.command("pipeline")
def health_pipeline() -> None:
    """Check pipeline status and show current retention timeframes."""
    typer.echo("pipeline jobs:")
    for job in CORE_JOBS:
        typer.echo(f"- {job}")
    settings = _settings()
    cutoffs = retention_cutoffs(
        datetime.now(UTC),
        RetentionPolicy(**settings.retention.model_dump()),
    )
    typer.echo("retention cutoffs:")
    for key, value in cutoffs.items():
        typer.echo(f"- {key}: {value.isoformat()}")
