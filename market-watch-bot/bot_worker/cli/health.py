from __future__ import annotations

from datetime import UTC, datetime

import typer
from sqlalchemy import func, select

from bot_worker.cli.apps import health_app
from bot_worker.cli.common import _echo_json, _run, _settings, _with_session
from bot_worker.db.models import AlertDecisionRecord, AlertDeliveryRecord
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


@health_app.command("alerts")
def health_alerts() -> None:
    """Check alert decision and delivery health."""
    async def action(session):
        pending_immediate = await session.scalar(
            select(func.count())
            .select_from(AlertDecisionRecord)
            .where(AlertDecisionRecord.decision == "immediate_alert")
            .where(AlertDecisionRecord.sent_at.is_(None))
        )
        failed_deliveries = await session.scalar(
            select(func.count())
            .select_from(AlertDeliveryRecord)
            .where(AlertDeliveryRecord.status == "failed")
        )
        latest_delivery = await session.scalar(
            select(AlertDeliveryRecord)
            .order_by(AlertDeliveryRecord.created_at.desc())
            .limit(1)
        )
        settings = _settings()
        _echo_json(
            {
                "pending_immediate_alerts": pending_immediate or 0,
                "failed_deliveries": failed_deliveries or 0,
                "default_channel": settings.alerts.default_channel,
                "telegram_bot_token_configured": bool(settings.telegram_bot_token),
                "telegram_chat_id_configured": bool(settings.telegram_chat_id),
                "latest_delivery": (
                    {
                        "id": latest_delivery.id,
                        "channel": latest_delivery.channel,
                        "status": latest_delivery.status,
                        "attempted_at": latest_delivery.attempted_at,
                        "error": latest_delivery.error_message,
                    }
                    if latest_delivery is not None
                    else None
                ),
            }
        )

    _run(_with_session(action))
