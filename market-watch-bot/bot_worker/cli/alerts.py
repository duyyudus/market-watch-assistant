from __future__ import annotations

from typing import Annotated

import typer
from sqlalchemy import select

from bot_worker.cli.apps import alert_app, alert_channel_app, alert_policy_app
from bot_worker.cli.common import _echo_json, _run, _settings, _with_session
from bot_worker.db.models import (
    AlertDecisionRecord,
    AlertDeliveryRecord,
    EventCluster,
)
from bot_worker.scoring import AlertThresholds, decide_alert
from bot_worker.services import AlertDeliveryConfig, dispatch_pending_alerts, send_test_alert
from bot_worker.services.alert_delivery import delivery_config_error


def _delivery_config(channel: str | None = None) -> AlertDeliveryConfig:
    return AlertDeliveryConfig.from_settings(_settings(), channel=channel)


@alert_policy_app.command("show")
def alert_policy_show() -> None:
    """Display the active alerting policy and scoring thresholds."""
    settings = _settings()
    _echo_json(
        {
            "immediate_threshold": settings.alerts.immediate_threshold,
            "watchlist_threshold": settings.alerts.watchlist_threshold,
            "digest_threshold": settings.alerts.digest_threshold,
            "default_channel": settings.alerts.default_channel,
        }
    )
@alert_policy_app.command("set")
def alert_policy_set(key: str, value: str) -> None:
    """Set an alerting policy parameter for this runtime (MVP placeholder)."""
    typer.echo(
        f"Policy setting {key}={value} accepted for runtime config; "
        "persistent edit is manual in MVP"
    )
@alert_policy_app.command("reset")
def alert_policy_reset() -> None:
    """Reset alerting policy to the defaults configured in settings.yml."""
    typer.echo("Alert policy reset uses defaults from settings.yml in MVP")


@alert_channel_app.command("show")
def alert_channel_show() -> None:
    """Display configured alert delivery channels."""
    settings = _settings()
    _echo_json(
        {
            "default_channel": settings.alerts.default_channel,
            "telegram_bot_token_configured": bool(settings.telegram_bot_token),
            "telegram_chat_id_configured": bool(settings.telegram_chat_id),
        }
    )


@alert_app.command("test")
def alert_test(score: Annotated[int, typer.Option("--score")] = 80) -> None:
    """Evaluate alerting decision (immediate, watchlist, or digest) for a hypothetical score."""
    settings = _settings()
    decision = decide_alert(
        score,
        AlertThresholds(
            immediate=settings.alerts.immediate_threshold,
            watchlist=settings.alerts.watchlist_threshold,
            digest=settings.alerts.digest_threshold,
        ),
    )
    _echo_json({"score": score, "decision": decision.decision, "reason": decision.reason})


@alert_app.command("send-test")
def alert_send_test(
    channel: Annotated[str, typer.Option("--channel")] = "telegram",
    message: Annotated[str, typer.Option("--message")] = "Market watch alert delivery test.",
) -> None:
    """Send a manual alert delivery test message."""
    config = _delivery_config(channel)
    error = delivery_config_error(config)
    if error:
        typer.echo(error)
        raise typer.Exit(1)

    async def action(session):
        result = await send_test_alert(session, config, message)
        _echo_json(result)
        return result

    result = _run(_with_session(action))
    if isinstance(result, dict) and result.get("status") == "failed":
        raise typer.Exit(1)


@alert_app.command("dispatch")
def alert_dispatch(
    channel: Annotated[str, typer.Option("--channel")] = "telegram",
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 20,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Dispatch pending immediate alerts to the configured channel."""
    config = _delivery_config(channel)
    error = delivery_config_error(config)
    if error and not dry_run:
        typer.echo(error)
        raise typer.Exit(1)

    async def action(session):
        result = await dispatch_pending_alerts(session, config, limit=limit, dry_run=dry_run)
        _echo_json(result)

    _run(_with_session(action))


@alert_app.command("list")
def alert_list(
    limit: Annotated[int, typer.Option("--limit", min=1, max=200)] = 20,
    level: Annotated[str | None, typer.Option("--level")] = None,
) -> None:
    """List recent alert decisions, optionally filtered by decision level."""
    async def action(session):
        stmt = (
            select(AlertDecisionRecord, EventCluster)
            .join(EventCluster, EventCluster.id == AlertDecisionRecord.event_cluster_id)
            .order_by(AlertDecisionRecord.created_at.desc())
            .limit(limit)
        )
        if level:
            stmt = stmt.where(AlertDecisionRecord.decision == level)
        rows = list((await session.execute(stmt)).all())
        if not rows:
            typer.echo("No alert decisions found")
            return
        for alert, event in rows:
            typer.echo(
                f"{alert.id}\t{alert.decision}\t{event.final_score}\t"
                f"{alert.channel or '-'}\t{alert.sent_at or '-'}\t{event.canonical_headline}"
            )

    _run(_with_session(action))
@alert_app.command("show")
def alert_show(identifier: str) -> None:
    """Display detailed reasons and metadata for a specific alert decision."""
    async def action(session):
        stmt = (
            select(AlertDecisionRecord, EventCluster)
            .join(EventCluster, EventCluster.id == AlertDecisionRecord.event_cluster_id)
            .where(AlertDecisionRecord.id == identifier)
        )
        row = (await session.execute(stmt)).first()
        if row is None:
            typer.echo("Alert decision not found")
            raise typer.Exit(1)
        alert, event = row
        delivery_status = None
        delivery_error = None
        delivery_stmt = (
            select(AlertDeliveryRecord)
            .where(AlertDeliveryRecord.alert_decision_id == alert.id)
            .order_by(AlertDeliveryRecord.created_at.desc())
            .limit(1)
        )
        delivery = await session.scalar(delivery_stmt)
        if delivery is not None:
            delivery_status = delivery.status
            delivery_error = delivery.error_message
        _echo_json(
            {
                "id": alert.id,
                "event_cluster_id": alert.event_cluster_id,
                "event": event.canonical_headline,
                "decision": alert.decision,
                "reason": alert.reason,
                "score": event.final_score,
                "score_breakdown": alert.score_breakdown,
                "channel": alert.channel,
                "sent_at": alert.sent_at,
                "latest_delivery_status": delivery_status,
                "latest_delivery_error": delivery_error,
                "suppression_reason": alert.suppression_reason,
                "created_at": alert.created_at,
            }
        )

    _run(_with_session(action))
